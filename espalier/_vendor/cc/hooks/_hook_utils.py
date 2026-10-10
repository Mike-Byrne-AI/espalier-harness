"""Minimal warning helpers for hook scripts.

Keeps observability consistent: fixed prefix lets tests assert on output.
Non-fatal by design — hooks call these and continue.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import posixpath
import re
import shlex
import stat
import sys
import threading
import time
import unicodedata
from collections.abc import Callable, Iterator, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # the annotation only; subprocess stays a lazy import (see below)
    import subprocess

# tools/cc for _json_safe: the dual-scope helper that renders an OSError's
# path as a path (DEF-799); `warn_exc` and every hook's crash guard read it
# from HERE. Guarded, because this import sits above every crash funnel: a
# `_json_safe.py` that is absent or predates the helper (an adopter's
# hand-patched copy is preserved as user-patched by the next upgrade while
# this file is refreshed) must degrade to Python's own rendering, never take
# the whole hook layer down at import.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from _json_safe import os_error_text  # noqa: E402
except ImportError:  # pragma: no cover - a stale or missing tools/cc/_json_safe.py
    def os_error_text(exc: BaseException) -> str:
        """Fallback when ``_json_safe`` lacks the helper: ``str(exc)`` unchanged."""
        return str(exc)
# The file-lock primitive every hook's lock site takes from HERE, guarded the
# same way: a `_json_safe.py` that predates it keeps POSIX on `flock` and makes
# a Windows lock site take its own unlocked degrade path (an OSError), never an
# import crash.
try:
    from _json_safe import lock_file, unlock_file  # noqa: E402
except ImportError:  # pragma: no cover - a tools/cc/_json_safe.py that predates the primitive
    def lock_file(fh: Any, *, shared: bool = False) -> None:
        """Fallback when ``_json_safe`` lacks the primitive: ``flock``, or ``OSError``."""
        if sys.platform == "win32":
            raise OSError("no file lock: tools/cc/_json_safe.py predates lock_file")
        import fcntl
        fcntl.flock(fh.fileno(), fcntl.LOCK_SH if shared else fcntl.LOCK_EX)

    def unlock_file(fh: Any) -> None:
        """Fallback twin of :func:`lock_file` above: Windows never took a lock."""
        if sys.platform == "win32":
            return
        import fcntl
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

# shutil / subprocess / tempfile are imported lazily inside the three functions
# that use them (host_orientation_line, check_branch, atomic_write_text). All
# three are session/subagent-start or write helpers — never on the per-tool-call
# path — so deferring them shaves ~9 ms/call off every PreToolUse('*') /
# PostToolUse('*') hook, which re-imports this shared module on every tool call.

# Matches `name = "..."` or `name = '...'` lines, leading whitespace OK.
_PYPROJECT_NAME_LINE = re.compile(r'^\s*name\s*=\s*["\']([^"\']+)["\']')


# Mutation-tool token set shared by PreToolUse/PostToolUse mutation
# matchers and the matcher-precision contract, defined once here so adding
# a new mutation tool updates one place (write_guard, plan_guard, and the
# matcher-precision test all read this). ``frozenset`` is hashable and
# immutable; consumers that need set ops (difference, intersection) work
# without copying.
MUTATION_TOOLS: frozenset[str] = frozenset({
    "Write", "Edit", "NotebookEdit", "Bash", "PowerShell",
})


class _DeniedExit(int):
    """Exit-0 sentinel that is TRUTHY.

    ``deny()`` returns this so a ``rc = check(...); if rc: return rc`` dispatch
    SHORT-CIRCUITS after a deny (the JSON decision is already on stdout), while
    ``int(rc)`` stays 0 so the hook still exits 0 per the channel-XOR protocol
    (a printed JSON decision REQUIRES exit 0; see docs/external/cc-hook-protocol.md).

    A plain ``0`` would make every ``if rc:`` after a deny FALSY, so the dispatch
    would run the NEXT check too -- double-printing a second decision JSON when one
    command matched two checks (``cp -s`` matches both the symlink check and the
    write-candidate extractor; a plan_guard MCP payload with two plan-gated leaves
    matched the per-leaf check twice). Two stdout JSONs corrupt the decision.
    """
    __slots__ = ()

    def __new__(cls) -> _DeniedExit:
        return super().__new__(cls, 0)

    def __bool__(self) -> bool:
        return True


# Singleton truthy-zero. Hooks: ``return _hook_utils.DENIED`` from deny(), and
# ``raise SystemExit(int(main()))`` so the exit code is a plain 0.
DENIED = _DeniedExit()


# Path-shaped fields an MCP tool_input may carry. write_guard sweeps every
# one for protected-zone mutations (a write, a delete, a move); plan_guard reads the same set for its
# plan-required check. Shared here so a move/rename via a non-canonical field
# — ``target``/``uri``/``src``/``dst``/``target_uri`` — cannot slip past one
# hook but not the other if either matcher widens.
# ``tests/test_*`` asserts both hooks read THIS tuple (no local re-definition).
MCP_PATH_FIELDS: tuple[str, ...] = (
    "path", "file_path", "destination", "new_path", "source",
    "src", "dst", "target", "uri", "target_uri",
)

# The protected-zone MCP check cannot be closed by enumerating a finite key set
# (a write keyed ``output_path`` slips past MCP_PATH_FIELDS) OR a finite nesting
# depth (``{files:[{path}]}``, ``{batch:{files:[{path}]}}`` nest arbitrarily). A
# finite union can't cover arbitrary keys + arbitrary depth, so the durable fix
# is a key-agnostic, depth-bounded leaf-walk over EVERY string leaf of an MCP
# tool_input. These bounds keep a pathological deeply-nested / very-wide payload
# from turning the PreToolUse scan into a slow-hook fail-open (the same failure
# class closed for the _PERL_OPEN_RE ReDoS critical). Exceeding either bound fails
# CLOSED — an unverifiable payload is denied, never waved through.
#
# The walk is O(total payload bytes) — the SAME complexity the json.loads that
# produced ``tool_input`` already paid — because normalize_path_str collapses
# ``..`` with posixpath.normpath (pure string), NOT Path.resolve() (whose
# per-component lstat over many/long leaves would itself be the slow-hook
# vector). Symlink-following is intentionally NOT done in the walk; that is the
# symlink-refusing reader's job (see read_text_nofollow).
MCP_LEAFWALK_MAX_DEPTH = 10
MCP_LEAFWALK_MAX_NODES = 10_000

# Keys whose DIRECT string value is DATA, not a write target — skipped by
# write_guard's key-agnostic leaf-walk so a content blob that lexically starts
# with a protected prefix (``content: "cc/ ..."``) does not spuriously deny.
# A nested write target keyed ``path`` UNDER a content key still resolves to
# the ``path`` governing-key (the immediate dict key), so it is NOT skipped —
# only a content key's own direct string leaf is. Residual: an MCP tool that
# used a content-named key as a direct path target would escape the friction
# layer (CI / harness-guard.yml still catches a committed write regardless).
MCP_CONTENT_KEYS: frozenset[str] = frozenset({
    "content", "contents", "text", "body", "data", "code",
    "snippet", "patch", "diff", "sql", "query", "message",
})


class MCPPayloadUnverifiable(Exception):
    """An MCP tool_input nests deeper / wider than the leaf-walk bounds.

    Raised by ``iter_mcp_path_leaves`` so the caller can fail CLOSED (deny /
    require-a-plan) rather than walk an unbounded structure or silently let an
    un-inspected leaf through.
    """


# Single-source symlink-refusing file reader. A hook that reads a GOVERNED
# state file (cc/execution_plan.json, the cc/ surface docs, .espalier state,
# settings) must NOT follow a symlink an attacker planted at that path --
# following it ingests attacker-controlled content (a symlinked plan whose
# target says status=in_progress OPENS the PreToolUse mutation gate).
# Consolidates the fd-level discipline previously hand-rolled in statusline.py
# + _freshness_cache.py into ONE chokepoint.
#
# Windows CPython omits O_NOFOLLOW / O_NONBLOCK (POSIX-only); getattr(...,0)
# degrades the OR to a no-op so the constant resolves everywhere, and the
# is_symlink() pre-check below is the (TOCTOU-bounded) Windows fallback.
_NOFOLLOW_OPEN_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
# A governed JSON/state file is tiny; an oversize read is treated as refusal.
NOFOLLOW_READ_MAX_BYTES = 1 << 20  # 1 MiB


def _has_symlink_ancestor(path: Path, within: Path) -> bool:
    """True if a directory strictly between ``within`` and ``path`` is a symlink.

    ``O_NOFOLLOW`` guards only the FINAL path component, so an intermediate
    symlinked governed directory (e.g. a symlinked ``cc/``) would still be
    FOLLOWED and let an attacker redirect the read. Walks ``path.parent`` up to
    ``within``; fail-closed (returns True) on any stat error.
    """
    try:
        cur = path.parent
        guard = 0
        while cur != within and guard < 64:
            if cur.is_symlink():
                return True
            parent = cur.parent
            if parent == cur:  # filesystem root reached without meeting `within`
                break
            cur = parent
            guard += 1
    except OSError:
        return True
    return False


def read_text_nofollow(path: Path, *, max_bytes: int = NOFOLLOW_READ_MAX_BYTES,
                       within: Path | None = None) -> str:
    """Read ``path`` as UTF-8, REFUSING to follow a final-component symlink.

    fd-level ``O_NOFOLLOW`` (POSIX) raises ``OSError`` (ELOOP) when the target
    is a symlink -- atomic, no TOCTOU. On Windows (``O_NOFOLLOW`` unavailable)
    an ``is_symlink()`` pre-check is the fallback. Also refuses a non-regular
    file (FIFO / socket / device via ``O_NONBLOCK`` + ``S_ISREG``) and content
    over ``max_bytes``.

    ``within``: when given (the repo root), ALSO refuse if any intermediate
    directory between ``within`` and ``path`` is a symlink -- ``O_NOFOLLOW``
    only protects the final component, so a symlinked governed PARENT dir would
    otherwise be followed.

    Raises ``FileNotFoundError`` when the path is absent and ``OSError`` for any
    other refusal (symlink / symlinked-ancestor / non-regular / oversize /
    unreadable) so callers can distinguish "missing" from "present-but-
    untrusted" and fail CLOSED on both -- and ``UnicodeDecodeError`` (a
    ``ValueError``, not an ``OSError``) when the bytes are not UTF-8: name it
    in the handler, or an ``except OSError`` lets it past (DEF-829).
    """
    if within is not None and _has_symlink_ancestor(path, within):
        raise OSError("refusing a symlinked ancestor directory")
    # Windows fallback: O_NOFOLLOW is a no-op there, so pre-check explicitly.
    if not getattr(os, "O_NOFOLLOW", 0) and path.is_symlink():
        raise OSError("refusing to follow a symlink")
    fd = os.open(str(path), _NOFOLLOW_OPEN_FLAGS)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise OSError("not a regular file")
        if st.st_size > max_bytes:
            raise OSError("file too large")
        raw = os.read(fd, max_bytes + 1)
        if len(raw) > max_bytes:
            raise OSError("file too large")
    finally:
        os.close(fd)
    return raw.decode("utf-8")


def has_active_plan(root: Path) -> bool:
    """True iff cc/execution_plan.json shows an OPEN mutation window:
    ``status == "in_progress"`` AND at least one step. Every other state
    (missing, malformed, non-dict, empty status/steps, non-UTF-8, a forged
    symlink) returns False so the caller fails CLOSED.

    Single owner unioning both prior copies' hardening:
    - symlink-REFUSING read (``read_text_nofollow(within=root)``) so a forged
      cc/execution_plan.json symlink — or a symlinked cc/ ancestor — cannot
      open the gate (from plan_guard._plan_state_label).
    - the full error domain (FileNotFoundError / OSError / UnicodeDecodeError /
      JSONDecodeError) plus a non-dict guard (unioning task_router's
      UnicodeDecodeError widening with plan_guard's), all failing closed.
    """
    plan_path = root / "cc" / "execution_plan.json"
    try:
        raw = read_text_nofollow(plan_path, within=root)
    except (FileNotFoundError, OSError, UnicodeDecodeError):  # fail-open: ok deliberate -- an unreadable plan is no plan: plan_guard then denies (the fail-closed direction) and the deny names the state
        return False
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):  # fail-open: ok deliberate -- an unparseable plan is no plan: plan_guard then denies and the deny names the state
        return False
    if not isinstance(data, dict):
        return False
    return data.get("status") == "in_progress" and bool(data.get("steps"))


# Canonical noqa annotation for governance-hook
# ``_integrity.append_audit`` swallow sites. All sister surfaces (4 hook
# source files + the AST contract test + ``docs/SHARP_EDGES.md`` +
# ``CHANGELOG.md``) reference this template. Order is ``BLE001, S110``
# for visual scan-ability (BLE001 is the structural rule; S110 is the
# downstream lint code). The reason must mention ``audit`` and ``hook``
# so the audit-best-effort intent is documented at every site.
# ``scripts/check_exception_policy.py`` parses the codes as a set
# (order-insensitive), but the template pins display order across all
# surfaces. Pinned by ``tests/test_noqa_template_parity.py``.
HOOK_AUDIT_NOQA_TEMPLATE = (
    "noqa: BLE001, S110 -- audit best-effort; "
    "hook protocol forbids stderr noise"
)


def resolve_project_root() -> Path:
    """Resolve ``CLAUDE_PROJECT_DIR`` to an absolute path.

    ``os.environ.get("CLAUDE_PROJECT_DIR", ".")`` returns ``""``
    if the variable EXISTS but is empty (rather than the ``"."`` default).
    Empty resolves to cwd, identical to the documented default, but the
    operator gets no notice that their env was ignored. If cwd is
    unrelated to the repo, protected-zone checks are computed against
    the wrong root silently. This helper warns on empty values, then
    falls back to the same cwd behavior.
    """
    return Path(_project_root_spelling()).resolve()


def _project_root_spelling() -> str:
    """``CLAUDE_PROJECT_DIR`` as a string ``Path`` can resolve correctly.

    The empty-value warning and cwd fallback documented on
    ``resolve_project_root``, then the Git Bash drive prefix translated on
    Windows (``_msys_drive_to_windows``, DEF-731). A root exported by hand from
    Git Bash -- ``CLAUDE_PROJECT_DIR=$(pwd)`` gives ``/c/<home>/repo`` there,
    which is how walk 2 drove the hooks -- is rooted but drive-less to
    ``ntpath``, so ``Path(raw).resolve()`` anchored it onto the current drive
    as the fabricated ``C:\\c\\<home>\\repo``. Against THAT root the
    untranslated leaf happened to relativise (both sides fabricated alike) and
    a translated leaf cannot, so translating the leaf alone would have turned
    a lucky DENY into an ALLOW: both sides of the compare translate, the way
    ``_bash_patterns._posix`` already treats target and root alike. Split
    from ``resolve_project_root`` so the translation is pinned on a POSIX
    test host without constructing a ``WindowsPath``. A native
    ``C:\\<home>\\...`` value passes through untouched.
    """
    raw = os.environ.get("CLAUDE_PROJECT_DIR")
    if raw is None or raw == "":
        if raw == "":
            # voice: debug-log Claude Code always sets the variable; an empty one is a hand-run hook's launch
            print(
                "[WARN] espalier: CLAUDE_PROJECT_DIR is empty; falling back "
                "to current working directory. Set it explicitly to remove "
                "this warning.",
                file=sys.stderr,
            )
        raw = "."
    return _msys_drive_to_windows(raw)


def warn(msg: str) -> None:
    """Emit a terse warning to stderr.

    Unified ``[WARN]`` prefix so log scrapers grepping for any single form
    catch every harness warning (otherwise an operator misses warnings
    depending on the grep pattern).

    On a hook that exits 0 -- every reporter, and every allow path of a
    blocking hook -- stderr reaches Claude Code's DEBUG LOG ONLY: Claude never
    sees it and the transcript never shows it (docs/external/cc-hook-protocol.md).
    A line someone must read goes through ``advise`` (the hook's JSON object)
    or ``say_once`` (a record), with this as its debug copy.
    """
    print(f"[WARN] espalier: {msg}", file=sys.stderr)  # voice: sink the stderr speaker itself; its callers pair it or declare


def warn_exc(prefix: str, exc: Exception) -> None:
    """Emit a terse warning with exception class and message. No traceback.
    An ``OSError``'s path is rendered as a path, not through ``repr``
    (``os_error_text``; DEF-799) -- the one place the hooks' handlers hand an
    exception to for rendering, so it is the one place that has to know.
    The debug log only, on an exit-0 path: see ``warn``."""
    print(f"[WARN] espalier: {prefix}: {type(exc).__name__}: {os_error_text(exc)}", file=sys.stderr)  # voice: sink the stderr speaker itself; its callers pair it or declare


# ── The seen advisory ────────────────────────────────────────────────────────
#
# An exit-0 hook's stderr reaches the debug log only (the protocol pin), so a
# reporter that wants Claude to read a line keeps it here and renders the
# collector into the additionalContext of the ONE stdout JSON object it prints
# -- the SessionStart banner (``take_advisories``), or a PostToolUse object
# (``emit_advisories``). The stderr copy stays, as the debug log's. Two stdout
# JSON lines fail the whole parse, which is why the hook renders once, at its
# end, and never per line. Shared helpers never collect: they run inside hooks
# that render nothing (tests/test_failopen_voice.py pins both rules).

_ADVISORIES: list[str] = []


def advise(line: str, *, echo: bool = True) -> None:
    """Keep ``line`` for this hook run's JSON object, and print it to stderr
    as the debug copy unless ``echo`` is false. ``line`` carries its own tag
    (``[WARN] ...``, ``[INFO] ...``), so the banner and the debug log read the
    same text. Never raises: a closed stderr costs the debug copy only."""
    _ADVISORIES.append(line)
    if not echo:
        return
    try:
        print(line, file=sys.stderr)  # voice: sink the collector's debug copy; the line is kept above for the JSON object
    except (OSError, ValueError):  # a closed or detached stderr: the kept line still renders
        pass


def advise_warn(msg: str) -> None:
    """``warn``'s seen twin: the same ``[WARN] espalier:`` line, kept."""
    advise(f"[WARN] espalier: {msg}")


def advise_exc(prefix: str, exc: BaseException) -> None:
    """``warn_exc``'s seen twin: the same line, kept."""
    advise(f"[WARN] espalier: {prefix}: {type(exc).__name__}: {os_error_text(exc)}")


def take_advisories() -> list[str]:
    """Every line kept since the last take, oldest first; empties the
    collector. A hook takes once at its start (a stale line from an in-process
    caller is not this run's) and once where it renders."""
    out = list(_ADVISORIES)
    _ADVISORIES.clear()
    return out


def emit_advisories(event: str, leading: Sequence[str] = (), operator: Sequence[str] = ()) -> None:
    """Print the hook's ONE stdout JSON object: ``leading`` then every kept
    line, joined as its additionalContext -- or nothing at all when every
    part is empty, so a quiet run stays a plain allow. Takes the collector.

    ``operator`` lines go to the person at the terminal as the object's
    ``systemMessage``, which Claude Code shows the user and not Claude; a hook
    opts in by passing them (post_write_check's zone report is the one caller), and
    every other hook's object is unchanged."""
    parts = [p for p in (*leading, *take_advisories()) if p]
    shown = [p for p in operator if p]
    if not parts and not shown:
        return
    obj: dict[str, Any] = {}
    if parts:
        obj["hookSpecificOutput"] = {
            "hookEventName": event,
            "additionalContext": "\n".join(parts),
        }
    if shown:
        obj["systemMessage"] = "\n".join(shown)
    print(json.dumps(obj))


# ── Self-host detection + context-driven prefix policy ───────────────────────


def _project_name_from_pyproject(text: str) -> str | None:
    """Extract project.name from pyproject.toml text via stdlib regex.

    Mirrors `espalier.surface_contract._project_name_from_pyproject` but
    avoids the `tomllib`/`tomli` import to keep `tools/cc/` third-party-free
    and stdlib-only on 3.10. Scans for `name = "..."` (or single-quoted)
    inside `[project]` or `[tool.poetry]` sections only — a dependency line
    like `dependencies = ["espalier-harness>=1.0"]` is not matched because
    it's neither in a target section nor a `name = ...` line.

    Returns None on anything unusual (multi-line strings, inline tables);
    `is_self_host_repo` then returns False, which yields user-repo
    behavior — the safer default.
    """
    in_target = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip()
            in_target = section in ("project", "tool.poetry")
            continue
        if not in_target:
            continue
        if (m := _PYPROJECT_NAME_LINE.match(line)):
            return m.group(1)
    return None


def _write_guard_prefix_matches_pin(root: Path) -> bool:
    """SHA-256 of write_guard.py's first 200 bytes vs the pinned hash.

    The pin is mirrored from ``espalier._self_host_fingerprint`` by the
    sibling ``_self_host_fingerprint.py`` module; byte-equality is
    asserted at import time by ``tests/test_self_host_fingerprint_parity.py``.
    Stdlib-only.
    """
    try:
        import _self_host_fingerprint  # type: ignore[import-not-found]
    except ImportError as exc:
        # The mirror lives in the same directory as _hook_utils.py; if it's
        # missing the hook can't verify the pin, so deny the signal (safer
        # default: treat as user-repo) -- and say so: on the self-host tree
        # this drops espalier/ and .github/workflows/ from the roster.
        say_once(
            root, "self-host-pin", "write_guard", "pretooluse_failed_open_self_host_pin",
            f"the self-host pin mirror could not be imported ({type(exc).__name__}); "
            "espalier/ and .github/workflows/ are not protected this session",
            fault=type(exc).__name__,
        )
        return False
    path = root / "tools" / "cc" / "hooks" / "write_guard.py"
    if not path.is_file():
        return False
    try:
        prefix = path.read_bytes()[: _self_host_fingerprint.WRITE_GUARD_PREFIX_BYTES]
    except OSError as exc:
        say_once(
            root, "self-host-pin-read", "write_guard", "pretooluse_failed_open_self_host_pin",
            f"write_guard.py could not be read for the self-host pin ({type(exc).__name__}); "
            "espalier/ and .github/workflows/ are not protected this session",
            fault=type(exc).__name__,
        )
        return False
    return (
        hashlib.sha256(prefix).hexdigest()
        == _self_host_fingerprint.WRITE_GUARD_PREFIX_SHA256
    )


def is_self_host_repo(root: Path) -> bool:
    """5-signal self-host detector. Mirrors espalier.surface_contract.is_self_host_repo.

    Signals (all required):
      1. ``espalier/`` is a directory
      2. ``tools/cc/`` is a directory
      3. ``bench/`` is a directory (adversarial corpus presence)
      4. ``pyproject.toml`` exists and name == espalier-harness
      5. SHA-256(first 200 bytes of write_guard.py) == pinned hash

    Stdlib-only (no espalier imports per isolation rule). The SHA pin is
    mirrored from ``espalier._self_host_fingerprint`` via the sibling
    ``_self_host_fingerprint.py``; parity at import time is asserted by
    ``tests/test_self_host_fingerprint_parity.py``.

    The hook side mirrors the library's 5-signal detector. False negative
    (treat self-host as user-repo) is the safer default for any signal mismatch.
    """
    if not (root / "espalier").is_dir():
        return False
    if not (root / "tools" / "cc").is_dir():
        return False
    if not (root / "bench").is_dir():
        return False
    pyproject = root / "pyproject.toml"
    if not pyproject.exists():
        return False
    try:
        # UnicodeDecodeError caught to match the SoT
        # (espalier.surface_contract.is_self_host_repo). This copy and
        # ci_guard's both omitted it, so a UTF-16 pyproject.toml raised out of
        # the detector instead of yielding the safe user-repo default. Driven
        # via ci_guard, whose merge gate exited 1 with a traceback; the same
        # input reaches this twin through every hook that asks about posture.
        # Deliberately NOT utf-8-sig: the SoT reads plain utf-8, so a BOM'd
        # file must classify as a user repo HERE TOO or the mirrors diverge.
        text = pyproject.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):  # fail-open: ok deliberate -- an unreadable pyproject classifies as a user repo, the safe posture
        return False
    name = _project_name_from_pyproject(text)
    if name is None:
        return False
    if name.strip().lower() not in {"espalier-harness", "espalier_harness"}:
        return False
    return _write_guard_prefix_matches_pin(root)


def harness_protected_prefixes(root: Path) -> list[str]:
    """Prefixes write_guard denies edits to. Self-host adds espalier/ and the
    full .github/workflows/ tree.

    `.github/workflows/` is self-host-only as a write_guard PREFIX.
    On an adopter repo the prefix would block them editing their OWN CI files
    (the governing-frame cardinal sin: a false-positive on user-owned code).
    The harness's own CI guard, `.github/workflows/harness-guard.yml`, stays
    universally write_guard-protected via _protected_zones.PROTECTED_FILES
    (exact match), so the seatbelt that can't-be-silently-edited is preserved.
    The CI-MERGE policy (tools/cc/ci_guard.py + the engine SoT) still protects
    the whole .github/workflows/ tree via the HARNESS-UPDATE-APPROVED marker --
    that is a separate, deliberate layer and is unchanged.
    """
    universal = [
        "tools/cc/",
        "cc/",
    ]
    if is_self_host_repo(root):
        return universal + [".github/workflows/", "espalier/"]
    return universal


# ── The once-a-session voice, and the adopter's own zones ────────────────────
#
# Fail-open stays allowed in the hooks (a toolbelt, not a security boundary);
# SILENT fail-open does not: a fault inside a guard that reads as "nothing
# found" is a defect the user cannot see. ``say_once`` is the voice a blocking
# hook uses for it -- one audit record (so ``/status --log`` counts it) and one
# stderr line per session per key. The adopter's ``protected_paths`` /
# ``generated_paths`` were documented as write protection and read by no hook
# (DEF-951); the readers below are what the guard consumes.

_SAID_THIS_PROCESS: set[str] = set()
ONCE_FLAG_PREFIX = "once_"   # session_start._clean_state_flags globs the family


def say_once(root: Path, key: str, hook: str, event_type: str, message: str, **details: object) -> None:
    """Speak about a fail-open once per session: a stderr line every time it
    would fire is noise, silence is the defect this exists to end. Writes one
    audit record (so ``/status --log`` counts it) and one stderr line, then a
    flag ``once_<key>`` under STATE_DIR; a later call with the same key in the
    same session does nothing. NEVER RAISES: every step sits in its own
    try/except, because this runs inside blocking hooks whose umbrella turns a
    raise into a crash-deny (``Path.exists`` propagates EACCES on an unreadable
    state dir below 3.14). When the flag cannot be written (a read-only state
    dir), the in-process set keeps it to once per hook process. ``details``
    are metadata only -- a fault's class name, a key, a count -- never a
    payload's text."""
    key = re.sub(r"[^A-Za-z0-9._-]", "_", str(key)) or "unnamed"
    if key in _SAID_THIS_PROCESS:
        return
    _SAID_THIS_PROCESS.add(key)
    flag: Path | None
    try:
        # A root that is not a Path (a str from a caller, a payload cwd) must
        # not raise here -- this line sat outside every try until the 2-A review.
        flag = (root if isinstance(root, Path) else Path(str(root))) / STATE_DIR / (ONCE_FLAG_PREFIX + key)
        if flag.exists():
            return
    # fail-open: ok deliberate -- an unusable root or an unreadable state dir: the in-process set keeps it to once per process, and the line below still prints
    except Exception:  # noqa: BLE001, S110 -- an unusable root or an unreadable state dir: the in-process set keeps it to once per process
        flag = None
    try:
        import _integrity  # lazy: _integrity imports this module at its top

        _integrity.append_audit(
            root,
            {"event_type": event_type, "details": {"hook": hook, "key": key, **details}},
            quiet=True,
        )
    except Exception:  # noqa: BLE001, S110 -- the record is best-effort; the line below still speaks
        pass
    try:
        print(f"[{hook}] {message}", file=sys.stderr)
    except Exception:  # noqa: BLE001, S110 -- a closed stderr must not turn an allow into a crash-deny
        pass
    try:
        if flag is not None:
            flag.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(flag, "")
    except Exception:  # noqa: BLE001, S110 -- a read-only state dir: once per process, not per session
        pass


def say_crash(hook: str, event_type: str, exc: BaseException, consequence: str) -> None:
    """A REPORTER's umbrella crash guard, said once a session (``say_once``):
    the hook exits 0, so its stderr line alone reaches the debug log only (the
    protocol pin), and the record is what ``/status --log`` counts. The root is
    resolved best-effort -- the crash may have been in resolving it -- and falls
    back to the working directory, where the record's once-flag then lands. The
    key carries the exception's class, so a second fault class is said too.
    Once a session for the record AND its stderr copy (``say_once``): a hook
    that crashes on every call leaves one record and one debug-log line per
    session per class, not one per call. A flag the previous session left is
    cleared by SessionStart's flag sweep, so a SessionStart that crashes before
    that sweep runs is said only when the class differs from the last
    session's. The record holds the class name only; the stderr copy adds the
    message. NEVER RAISES. The four blocking hooks' guards fail CLOSED through
    their own audited funnels instead."""
    try:
        root = resolve_project_root()
    except BaseException:  # noqa: BLE001 -- best-effort; the working directory then
        root = Path(".")
    try:
        detail = f"{type(exc).__name__}: {os_error_text(exc)}"
    except Exception:  # noqa: BLE001 -- an exception that cannot render itself still has a class
        detail = type(exc).__name__
    # The stderr copy keeps the crash guards' `[ERROR] <hook> crashed: <class>`
    # shape, the one a log scraper greps for across every hook.
    say_once(
        root, f"{hook}-crash-{type(exc).__name__}", hook, event_type,
        f"[ERROR] {hook} crashed: {detail}; {consequence}",
        fault=type(exc).__name__,
    )


_UNBOUND: Any = object()
_TOML_PARSER: Any = _UNBOUND


def _toml_parser() -> Any:
    """``tomllib`` (3.11+), else ``tomli``, else ``None`` -- bound on first use,
    so the import stays off the per-tool-call path of a tree with no
    espalier.toml (every PreToolUse('*') hook fire re-imports this module)."""
    global _TOML_PARSER
    if _TOML_PARSER is _UNBOUND:
        try:
            import tomllib as parser  # type: ignore[import-not-found]
        except ImportError:  # fail-open: ok deliberate -- no TOML parser importable: the regex arm of read_toml_string_list serves the key
            try:
                import tomli as parser  # type: ignore[no-redef]
            except ImportError:
                parser = None  # type: ignore[assignment]
        _TOML_PARSER = parser
    return _TOML_PARSER


def read_toml_table(
    root: Path, *, parser: Any = _UNBOUND, on_error: Callable[[str], None] | None = None,
) -> dict | None:
    """The parsed top-level table of ``<root>/espalier.toml``: ``None`` when the
    file is absent, no parser is importable, or the file is malformed -- in
    which case ``on_error`` (the caller's channel) is told why, with the
    exception rendered through ``os_error_text``. ``parser`` is injectable so a
    caller can pass its own binding (``plan_guard._tomllib``, which its tests
    monkeypatch to force the regex arm of ``read_toml_string_list``). Never
    raises."""
    if parser is _UNBOUND:
        parser = _toml_parser()
    if parser is None:
        return None
    try:
        try:
            with open(root / "espalier.toml", "rb") as fh:
                data = parser.load(fh)
        except TypeError:
            # tomli below 1.1 types load() for a text handle and raises on
            # the binary one (DEF-871: measured on CPython 3.10 with tomli
            # 1.0.4, where any espalier.toml sent every source write to
            # plan_guard's crash handler; 1.2.3 reads the binary handle).
            # Read it the way that parser wants rather than let the error
            # reach the caller's crash handler. A TypeError from the retry
            # is a parser that takes neither handle: the arm below reports
            # it through on_error and returns None, so this never raises.
            with open(root / "espalier.toml", encoding="utf-8") as fh:
                data = parser.load(fh)
    except FileNotFoundError:  # fail-open: ok deliberate -- an absent espalier.toml is not a fault
        return None
    # fail-open: ok deliberate -- the caller's channel (on_error) is told when the caller bound one; plan_guard's re-read binds none because its first read already spoke
    except (OSError, ValueError, TypeError) as exc:  # TOMLDecodeError is a ValueError
        if on_error is not None:
            on_error(os_error_text(exc))
        return None
    return data if isinstance(data, dict) else None


def _regex_extract_string_list(text: str, key: str) -> list[str] | None:
    """Best-effort stdlib fallback for a flat ``key = ["a", "b"]`` list when no
    TOML parser is importable (a Python < 3.11 hook interpreter without
    ``tomli``): full-line ``#`` comments are stripped, then the one flat key is
    recovered by regex. It does not reimplement TOML -- table-scoped or
    duplicate keys and quote/bracket characters inside a value can diverge
    from a real parse. ``None`` when the key is absent."""
    text = re.sub(r"(?m)^\s*#.*$", "", text)
    # Only the top-level region: stop at the first table header, so a
    # table-scoped key is not read as top-level. Anchored at line start, so
    # `unprotected_paths = [...]` and a key inside a trailing comment do not
    # match -- this arm now creates DENIES (the adopter zones), and an
    # over-match on a no-parser host is a false deny on user-owned code.
    header = re.search(r"(?m)^[ \t]*\[", text)
    if header is not None:
        text = text[: header.start()]
    m = re.search(r"(?m)^[ \t]*" + re.escape(key) + r"[ \t]*=[ \t]*\[(.*?)\]", text, re.DOTALL)
    if m is None:
        return None
    return re.findall(r"""["']([^"']*)["']""", m.group(1))


def read_toml_string_list(
    root: Path, key: str, *, parser: Any = _UNBOUND, on_error: Callable[[str], None] | None = None,
) -> object | None:
    """The RAW value of the flat top-level ``key`` in ``<root>/espalier.toml``:
    ``None`` when the file or the key is absent, or the file is malformed (then
    ``on_error`` was told why). No validation -- the value is whatever TOML
    parsed, so the ``isinstance(raw, list)`` check and any entry validator stay
    with the caller, which is why the annotation is ``object``. Three arms:
    ``tomllib``, ``tomli``, and the regex fallback when neither imports. The
    hook-side reader of a FLAT key; ``plan_guard`` and ``write_guard`` both
    route through it, and ``stop_gate`` reads its ``[extra_actions]`` table through
    ``read_toml_table`` beside it (since 2026-10-08). Never raises."""
    config_path = root / "espalier.toml"
    try:
        present = config_path.is_file()
    except OSError as exc:  # fail-open: ok deliberate -- the caller's channel (on_error) is told; a file that cannot be stat-ed is reported, not read as absent
        # A file that cannot even be stat-ed is not "absent": the caller's
        # channel is told, so a zone it names is not silently unprotected.
        if on_error is not None:
            on_error(os_error_text(exc))
        return None
    if not present:
        return None
    if parser is _UNBOUND:
        parser = _toml_parser()
    if parser is None:
        try:
            text = config_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:  # fail-open: ok deliberate -- the caller's channel (on_error) is told when the caller bound one
            if on_error is not None:
                on_error(os_error_text(exc))
            return None
        return _regex_extract_string_list(text, key)
    data = read_toml_table(root, parser=parser, on_error=on_error)
    if data is None:
        return None
    return data.get(key)


ADOPTER_ZONE_KEYS: tuple[tuple[str, str], ...] = (
    ("protected_paths", "protected"),
    ("generated_paths", "generated"),
)


_ADOPTER_ZONES_MEMO: dict[str, tuple[tuple[int, int], tuple[tuple[str, str], ...]]] = {}


def adopter_protected_prefixes(root: Path) -> tuple[tuple[str, str], ...]:
    """``(prefix, kind)`` pairs from espalier.toml: kind is ``"protected"`` for
    ``protected_paths`` ("never touch") and ``"generated"`` for
    ``generated_paths`` ("read-only; regenerate, do not hand-edit"). Empty on a
    tree with neither key. Read on every call, like ``plan_exempt_prefixes``:
    the adopter edits the file and expects the next write to see it. Each
    prefix ends in ``/`` and is matched at a path boundary by the consumers, so
    ``data`` never covers ``database.py``. A value that is not a list of
    strings, an entry that would cover the whole tree or leave it, and an
    absolute entry are ignored -- and SAID, once a session (``say_once``),
    because a setting the user wrote that does nothing is the defect. Never
    raises: this runs under a blocking hook's umbrella, and a raise here would
    deny every call."""
    def _unreadable(text: str) -> None:
        say_once(
            root, "zone-toml", "write_guard", "config_zone_unreadable",
            f"espalier.toml could not be parsed ({text}); protected_paths / "
            "generated_paths protect nothing this session",
        )

    config_path = (root if isinstance(root, Path) else Path(str(root))) / "espalier.toml"
    try:
        st = config_path.stat()
        stamp: tuple[int, int] | None = (st.st_mtime_ns, st.st_size)
    except OSError:  # fail-open: ok deliberate -- absent or unreadable: the reader below decides and speaks
        stamp = None
    memo_key = str(config_path)
    if stamp is not None:
        hit = _ADOPTER_ZONES_MEMO.get(memo_key)
        if hit is not None and hit[0] == stamp:
            return hit[1]
    else:
        _ADOPTER_ZONES_MEMO.pop(memo_key, None)

    parser = _toml_parser()
    table: dict | None = None
    if parser is not None:
        # One parse per call, not one per key: this runs on every mutating
        # tool call, once per extracted path (the 2-A code review measured it).
        table = read_toml_table(root, parser=parser, on_error=_unreadable)
    out: list[tuple[str, str]] = []
    for key, kind in ADOPTER_ZONE_KEYS:
        if parser is not None:
            raw = table.get(key) if table is not None else None
        else:
            raw = read_toml_string_list(root, key, parser=None, on_error=_unreadable)
            if raw is not None:
                say_once(
                    root, f"zone-{key}-degraded-reader", "write_guard", "config_zone_degraded_reader",
                    f"espalier.toml: {key} read by the no-parser regex fallback (Python < 3.11 "
                    "without tomli); a zone it recovers may differ from a real parse",
                )
        if raw is None:
            continue
        if not isinstance(raw, list) or not all(isinstance(entry, str) for entry in raw):
            say_once(
                root, f"zone-{key}", "write_guard", "config_zone_ignored",
                f"espalier.toml: {key} must be a list of strings, got "
                f"{type(raw).__name__}; it protects nothing",
            )
            continue
        for i, entry in enumerate(raw):
            spelled = entry.replace("\\", "/").strip()
            if spelled.startswith("/") or re.match(r"^[A-Za-z]:", spelled):
                say_once(
                    root, f"zone-{key}-absolute-{i}", "write_guard", "config_zone_ignored",
                    f"espalier.toml: {key} entry {entry!r} is not repo-relative; ignored",
                )
                continue
            while spelled.startswith("./"):
                spelled = spelled[2:]
            spelled = spelled.strip("/")
            if not spelled or spelled == "." or ".." in spelled.split("/"):
                say_once(
                    root, f"zone-{key}-tree-{i}", "write_guard", "config_zone_ignored",
                    f"espalier.toml: {key} entry {entry!r} would cover the whole tree "
                    "or leave it; ignored",
                )
                continue
            out.append((spelled + "/", kind))
    if not out and table is not None:
        # A mistyped key NAME is the pack's own thesis unenforced at the hook:
        # the engine warns only when a CLI command runs. Same cutoff as
        # config.load_config.
        import difflib

        wanted = [key for key, _ in ADOPTER_ZONE_KEYS]
        for present in table:
            if present in wanted:
                continue
            near = difflib.get_close_matches(str(present), wanted, n=1, cutoff=0.6)
            if near:
                say_once(
                    root, f"zone-typo-{present}", "write_guard", "config_zone_ignored",
                    f"espalier.toml: `{present}` is not a key the guard reads "
                    f"(did you mean `{near[0]}`?); it protects nothing",
                )
    result = tuple(out)
    if stamp is not None:
        _ADOPTER_ZONES_MEMO[memo_key] = (stamp, result)
    return result


def adopter_zone_for(rel_path: str, root: Path) -> tuple[str, str] | None:
    """``(prefix, kind)`` of the adopter zone a repo-relative path sits in, at a
    path boundary (``data/x`` and the bare ``data`` match ``data/``;
    ``database.py`` does not), case-folded like ``_protected_zones``'s checks;
    ``None`` outside every adopter zone."""
    rel = rel_path.replace("\\", "/").strip("/")
    while rel.startswith("./"):
        rel = rel[2:]
    rel_cf = unicodedata.normalize("NFKC", rel).casefold()
    for prefix, kind in adopter_protected_prefixes(root):
        pcf = unicodedata.normalize("NFKC", prefix).casefold()
        if rel_cf == pcf.rstrip("/") or rel_cf.startswith(pcf):
            return prefix, kind
    return None


def protected_prefixes(root: Path) -> list[str]:
    """The prefixes the write guard denies on every channel: the harness zones
    (``harness_protected_prefixes``) followed by the adopter's
    ``protected_paths`` ("never touch"). ``generated_paths`` is NOT here: it is
    refused on the Write / Edit / NotebookEdit channel only
    (``write_guard.check_write_edit``), so a build's own ``rm -rf dist`` or
    regeneration step is never blocked. The inode backstop
    (``_protected_zones._protected_not_allowed_inodes``) walks the harness
    roster alone: it is bounded by a node budget whose exhaustion fails
    closed, and an adopter's data tree can exhaust it."""
    return harness_protected_prefixes(root) + [
        prefix for prefix, kind in adopter_protected_prefixes(root) if kind == "protected"
    ]


# ── The spawn chokepoint ──────────────────────────────────────────────────────
#
# A gate that spawns a program the operator named (the stop-time test
# override, the plain pytest branch, the blueprint finalize) routes through
# ``spawn_checked``: argv[0] is resolved first -- through ``shutil.which``, so a
# Windows script shim (``npm`` is ``npm.cmd``) is found (DEF-948) -- and a
# program that cannot start comes back as a ``SpawnFailure`` instead of a
# raise, so every caller must decide what to SAY. Reporters keep their own
# ``subprocess.run`` under a ``# spawn: ok <reason>`` declaration; the
# population test walks both.

_CMD_SHIM_METACHARS = frozenset("&|<>^%")
STOP_GATE_TEST_CMD_ENV = "ESPALIER_STOP_GATE_TEST_CMD"


def stop_gate_test_cmd() -> str:
    """The stop-time test override as the operator set it (empty when unset):
    one owner, so the gate and the banner read the same variable."""
    return os.environ.get(STOP_GATE_TEST_CMD_ENV, "")


class SpawnFailure:
    """A program that did not start. ``error`` is the exception's class name,
    or ``Unresolved`` (argv[0] names no program), ``EmptyCommand``,
    ``UnbalancedQuotes`` (the command could not be split), ``ShellSyntax``
    (a token no shell interprets here -- ``&&``, a pipe, a redirection -- so
    the entry would start its first program alone; refused by the stop gate
    before it starts), or
    ``CmdShimMetachar`` (a Windows .cmd/.bat shim re-parses its line, so an
    argument carrying ``&``, ``|``, ``<``, ``>``, ``^`` or ``%`` could run a
    different command; refused before it starts). Never the exception's
    message: a message can quote a path. ``resolved`` is what the resolver
    returned for argv[0], or None; ``detail`` is ``os_error_text(exc)``, the
    errno and strerror with a path rendered safely. A plain class, not a
    dataclass: a dozen tests path-load this module with ``exec_module`` before
    registering it in ``sys.modules``, which a dataclass decorator cannot
    survive on Python 3.14 (memory: register the module before exec)."""

    __slots__ = ("argv", "error", "resolved", "detail")

    def __init__(
        self, argv: tuple[str, ...], error: str, resolved: str | None, detail: str | None = None,
    ) -> None:
        self.argv = tuple(argv)
        self.error = error
        self.resolved = resolved
        self.detail = detail

    def __repr__(self) -> str:
        return (
            f"SpawnFailure(argv={self.argv!r}, error={self.error!r}, "
            f"resolved={self.resolved!r}, detail={self.detail!r})"
        )

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SpawnFailure) and (
            (self.argv, self.error, self.resolved, self.detail)
            == (other.argv, other.error, other.resolved, other.detail)
        )

    @property
    def resolution(self) -> str:
        """The clause a reason carries: whether argv[0] resolved at all, and
        to what -- "did not resolve" and "resolved to X and still could not
        start" read differently and are fixed differently."""
        token = self.argv[0] if self.argv else "(empty)"
        if self.error == "EmptyCommand":
            return "the command is empty"
        if self.error == "UnbalancedQuotes":
            return "the command could not be split (unbalanced quotes)"
        if self.error == "ShellSyntax":
            return (
                "the command carries shell syntax (`&&`, `||`, `|`, `;`, a redirection, "
                "`$(` or a backtick), which no shell interprets here"
            )
        if self.error == "Unresolved":
            return f"`{token}` did not resolve to a program"
        if self.error == "CmdShimMetachar":
            return (
                f"`{token}` resolved to `{self.resolved}`, a script shim that re-parses its "
                "arguments, and an argument carries a shell metacharacter"
            )
        return f"`{token}` resolved to `{self.resolved}` and still could not start"


def split_command(text: str) -> list[str]:
    """One splitter for the stop gate and the banner, so the two never disagree
    on a quoted path. ``posix=False`` on Windows is required, not cosmetic: in
    POSIX mode ``shlex.split`` treats ``\\`` as an escape, so a native path
    ``C:\\Python\\python.exe`` is rewritten to ``C:Pythonpython.exe`` and the
    spawn fails on a path the operator never typed; ``posix=False`` keeps the
    quotes in the tokens, so they are stripped afterwards. Raises ``ValueError``
    on unbalanced quotes, as ``shlex`` does; callers say so."""
    if os.name == "nt":
        return [
            tok[1:-1] if len(tok) > 1 and tok[0] == tok[-1] and tok[0] in "\"'" else tok
            for tok in shlex.split(text, posix=False)
        ]
    return shlex.split(text)


def resolve_program(token: str, *, root: Path) -> str | None:
    """argv[0] to the path that would start, or None. A token holding a path
    separator resolves against ``root`` (never the hook process's cwd -- the
    relative-override fix of 2026-09-29 must survive); a bare token through
    ``shutil.which``, which honours PATHEXT on Windows so ``npm`` finds
    ``npm.cmd``."""
    import shutil

    if not token:
        return None
    if os.path.isabs(token) or "/" in token or (os.name == "nt" and "\\" in token):
        # The root's own Path class: a bare Path() call under an emulated
        # os.name builds the other platform's class and raises on this one.
        path_cls = type(root) if isinstance(root, Path) else Path
        candidate = path_cls(token) if os.path.isabs(token) else path_cls(str(root)) / token
        found = shutil.which(str(candidate))
        if found:
            return found
        try:
            return str(candidate) if candidate.is_file() else None
        except OSError:  # fail-open: ok deliberate -- a candidate that cannot be stat-ed is unresolved, and the gate that asked says so
            return None
    return shutil.which(token)


def spawn_checked(
    argv: Sequence[str], *, root: Path, **kwargs: Any,
) -> "subprocess.CompletedProcess[Any] | SpawnFailure":
    """The spawn a gate routes through. Resolves argv[0] (``resolve_program``)
    and refuses a Windows script shim with a metacharacter argument, then runs
    the resolved argv; a program that cannot start returns a ``SpawnFailure``
    instead of raising, so the caller decides what to say. ``TimeoutExpired``
    propagates as today. ``kwargs`` are ``subprocess.run``'s."""
    import subprocess

    argv = [str(a) for a in argv]
    if not argv:
        return SpawnFailure((), "EmptyCommand", None)
    resolved = resolve_program(argv[0], root=root)
    if resolved is None:
        return SpawnFailure(tuple(argv), "Unresolved", None)
    if os.name == "nt" and resolved.lower().endswith((".cmd", ".bat")) and any(
        ch in arg for arg in argv[1:] for ch in _CMD_SHIM_METACHARS
    ):
        return SpawnFailure(tuple(argv), "CmdShimMetachar", resolved)
    try:
        # Two pragma vocabularies meet here on purpose: `subprocess-contract: ok`
        # answers the subprocess_contracts scanner (is this espalier-CLI argv
        # pinned?); `spawn: ok` answers tests/test_spawn_chokepoint.py (is this
        # raw spawn declared?). This call is the chokepoint itself, so it needs
        # the first and is exempt from the second by position.
        # subprocess-contract: ok the chokepoint -- argv is the caller's, argv[0] resolved above; an espalier-signature spawn that routes here carries its own pin at its call site
        return subprocess.run([resolved, *argv[1:]], **kwargs)
    except subprocess.TimeoutExpired:
        raise
    except (OSError, ValueError) as exc:  # ValueError: a NUL in an argument
        return SpawnFailure(tuple(argv), type(exc).__name__, resolved, os_error_text(exc))


# Universal plan-exempt prefixes: paths under these skip plan_guard's plan-required
# check regardless of repo context. Single owner for the set that plan_guard's
# doc-pinned EXEMPT_PREFIXES literal mirrors (bound by test_forced_copy_parity).
# espalier/ is deliberately NOT here — on a user repo it may be user code that MUST
# keep plan discipline; harness_exempt_prefixes adds it ONLY on the self-host repo.
EXEMPT_UNIVERSAL_PREFIXES = (
    "tests/", ".claude/", "tools/cc/", "cc/", "reports/", "memory/", "docs/",
    "task-packs/",
    # The hooks' own state dir: the hygiene gates' deny messages tell the reader
    # to write a relief record there by hand, and at Stop time no plan is active
    # by construction -- so a Write there must not need one (driven 2026-09-07).
    ".espalier-state/",  # == STATE_DIR (defined below) + "/"; pinned equal by test
)


def stack_test_roots(root: Path) -> list[str]:
    """The test roots of the stacks whose manifests sit at ``root``, sorted,
    minus the universal prefixes: the conditional member of the plan guard's
    exempt set on an adopter tree, so a Node adopter's ``test/`` is exempt the
    way a Python adopter's ``tests/`` always was. Read from the
    table through ``STACK_TEST_DIRS``: ``test/``, ``tests/``, ``__tests__/``
    and ``spec/`` beside a ``package.json``; ``tests/`` and ``test/`` beside a
    Python manifest; ``tests/`` beside ``Cargo.toml``; nothing for Go, whose
    ``_test.go`` files sit beside source. One directory listing, never a probe
    per name; an unreadable root is no roots. Never raises."""
    try:
        with os.scandir(root) as entries:
            present = {entry.name for entry in entries if entry.is_file()}
    except OSError:  # fail-open: ok deliberate -- an unlistable root names no manifest, so no stack root is exempt: the guard denies MORE, not less, and the root-file gate reads the same listing
        return []
    roots: set[str] = set()
    for manifest, dirs in STACK_TEST_DIRS.items():
        if manifest in present:
            roots.update(dirs)
    return sorted(roots - set(EXEMPT_UNIVERSAL_PREFIXES))


def harness_exempt_prefixes(root: Path) -> list[str]:
    """Prefixes plan_guard exempts from plan-required check.

    On a user repo, espalier/ is potentially user code, so plan discipline
    applies, and the test roots of the stack whose manifest sits at the root
    join the universal set (``stack_test_roots``). On self-host, espalier/ is
    our source — same exempt logic as the rest of the harness internals — and
    the stack roots do not apply: this tree's ``tests/`` is universal already.
    """
    universal = list(EXEMPT_UNIVERSAL_PREFIXES)
    if is_self_host_repo(root):
        return universal + ["espalier/"]
    return universal + stack_test_roots(root)


def harness_excluded_prefixes(root: Path) -> list[str]:
    """Prefixes reflect_trigger excludes from auto-reflect tracking.

    On self-host, harness paths ARE source — include them so dogfood-reflect
    walks real code. On a user repo, harness paths are infrastructure —
    exclude.
    """
    universal = [
        "tests/",
        ".claude/",
        "cc/",
        "reports/",
    ]
    if is_self_host_repo(root):
        return universal
    return universal + ["tools/cc/", "espalier/"]


# ── Seeded scaffolds: presence is not content ────────────────────────────────


SEEDED_PLACEHOLDER_BODIES: dict[str, tuple[str, ...]] = {
    # ``espalier/assets/seed/SHARP_EDGES.md`` ships exactly this one section and
    # asks the operator to delete it once they have written a real edge. The
    # value is EVERY body this seed has ever shipped under this heading, oldest
    # first, the live one LAST -- append-only, never replaced. The predicate
    # measures what a section says beyond the seed, and the seed an adopter has
    # is the one on THEIR tree: since 2026-07-25 ``init`` refreshes an untouched
    # stamped copy to HEAD, but an edited or unstamped copy (a fusion's stub, a
    # pre-2026-07-25 install) keeps the body it was written with, so a matcher
    # pinned to HEAD alone would read every such scaffold as the operator's
    # content (found by the adversarial pass on the first cut, which pinned
    # forward to HEAD only; the population this history serves narrowed to the
    # edited and unstamped copies on 2026-09-11, DEF-432).
    # The live body is pinned whitespace-flattened against the seed asset, and
    # the history length is pinned, by test_session_banner.py::
    # TestFootgunPointerContentOracle::test_placeholder_titles_match_the_seed_corpus.
    "Add your first sharp edge here": (
        "A sharp edge = the footgun + the mistake it prevents + a one-line way to\n"
        "prove you have hit it. Write one the first time something surprises you \u2014\n"
        "that is the moment the detail is still in your head.\n"
        "\n"
        "Delete this placeholder section once you have a real one.",
    ),
}
"""Seeded scaffold sections, title -> every body ``init`` has deployed under it.

Single owner for every hook that reads a SEEDED doc, because presence and
content are different questions and ``init`` deploys some docs near-empty. Two
consumers read the same file and must agree: ``session_start._footgun_pointer``
(may the banner NAME this catalog?) and ``_recall._load_corpus`` (may this
section be RETRIEVED?). A divergent copy is how one of them ends up advertising
a scaffold the other correctly suppresses.

Embedded rather than read from the seed asset at runtime because this module
runs standalone on an adopter tree, where the seed lives inside the installed
``espalier`` package and may not be importable from a hook. When the seed BODY
is reworded, APPEND the new body; when the seed HEADING is reworded, ADD the new
title as another key. Nothing is ever removed: an adopter's tree carries
whichever heading and body ``init`` wrote there, and a matcher that forgot
either would advertise their untouched scaffold as a catalog on the next
upgrade -- the same defect on the other axis, found by the adversarial pass
after the body history landed.
"""

SEEDED_PLACEHOLDER_TITLES: frozenset[str] = frozenset(SEEDED_PLACEHOLDER_BODIES)
"""Section titles that MAY mean "nobody has filled this in yet" -- derived from
``SEEDED_PLACEHOLDER_BODIES``; see ``is_seeded_placeholder``."""

SEEDED_PLACEHOLDER_SENTINEL = "Delete this placeholder section once you have a real one."
"""The scaffold's own self-description -- the last line of the seeded body.

Kept as a named constant because the seed asset and the banner tests both key on
it, but it is no longer the discriminator. It was, and that was the defect
(DEF-560): a section is still the scaffold whether or not this one sentence
survives the operator's edits, and an operator who writes their first edge ABOVE
it without deleting it has real content, not a scaffold. The discriminator is
what the section says beyond the seed -- ``SEEDED_NEW_CONTENT_FLOOR``.
"""

SEEDED_NEW_CONTENT_FLOOR = 3
"""How many distinct words a section must add beyond its seed body to count as
real content.

⚠ Name the mutation this separates, because no constant separates every case.
Below the floor is annotation, not content: ``TODO``, ``WIP``, a reworded or
punctuation-drifted sentinel, a title-cased heading -- every realistic edit an
operator makes to a scaffold they have not yet filled in adds zero, one or two
new words (measured over thirteen such edits before the fix; seven of them
flipped the old sentinel-only predicate). At or above it is prose: the shortest
sharp edge anyone would write is a sentence, and a sentence about a footgun
carries at least three words the seed's own prose does not (a command, a
symptom, a consequence). A two-word fragment under the seeded heading is the
one shape this reads wrongly, and it reads it as "not filled in yet", which is
the honest reading of a two-word fragment. "Words" is per ``_content_words``:
for scripts written without spaces one character is a unit, so the bar is
comparable across scripts rather than ten times stricter for Chinese.
"""

def _flatten_ws(text: str) -> str:
    """Collapse all runs of whitespace to single spaces.

    Wrapping is behaviour when prose is matched by substring: an operator (or a
    formatter) rewrapping the sentinel across a newline must not silently turn
    the filter off.
    """
    return " ".join(text.split())


_WORD_RE = re.compile(r"\w+")

#: A code block the seed never had: a NON-EMPTY backtick or tilde fence -- the
#: opening fence, any blank lines, then a line that is not the closing fence.
#: Fences only, deliberately. A first cut also counted a four-space-indented
#: line as code, and the adversarial pass showed that reads ordinary markdown
#: as content: a nested bullet under the scaffold, a list continuation, a
#: blockquote, or the seed's own prose re-indented by an editor all advertised
#: the untouched scaffold as a catalog -- the DEF-560 harm re-opened by its fix.
#: An indented block cannot be told from those without a markdown parser, so
#: an indented one-line repro falls back to the word count (three new words
#: shows it; most commands have them), and the seed's own advice is a fence.
#: The first cut also required the code on the line right after the fence, so
#: a fence opened with a blank line hid a real repro; any run of blank lines is
#: now skipped before the content line is looked for.
_CODE_BLOCK_RE = re.compile(
    r"(?:^|\n)(?:```|~~~)[^\n]*\n(?:[ \t]*\n)*"          # opening fence, blank lines
    r"(?![ \t]*(?:```|~~~)[ \t]*(?:\n|$))[ \t]*\S"        # then a real line, not the closer
)


#: Scripts written without spaces between words -- CJK ideographs, hiragana and
#: katakana, Thai. ``\w+`` returns a whole clause of these as ONE token, so a
#: two-clause Chinese first edge counted as two "words" and fell under the floor
#: (the adversarial pass drove it: hidden from both consumers, where the old
#: sentinel rule had shown it). One character is the honest unit there.
_UNSPACED_SCRIPT_RE = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u0e00-\u0e7f]"
)


def _content_words(text: str) -> set[str]:
    """Distinct case-folded content units -- the thing the seed-residual
    comparison counts. Space-delimited scripts contribute words of two or more
    characters; unspaced scripts contribute one unit per character. Punctuation
    and wrapping do not survive it, which is the point: a formatter or a stray
    period must not move the verdict."""
    units: set[str] = set()
    for tok in _WORD_RE.findall(text.casefold()):
        if _UNSPACED_SCRIPT_RE.search(tok):
            units.update(_UNSPACED_SCRIPT_RE.findall(tok))
            units.update(w for w in _UNSPACED_SCRIPT_RE.sub(" ", tok).split() if len(w) > 1)
        elif len(tok) > 1:
            units.add(tok)
    return units


def _normalize_seed_title(title: str) -> tuple[str, ...]:
    """The heading's words, in order, case-folded -- and nothing else.

    Case, closing ATX hashes, a trailing question mark or colon, quotes and
    wrapping are edits an operator makes to a heading without touching what it
    says, so none of them may move the verdict. A hand-picked punctuation class
    was the first cut and it under-delivered its own docstring (``?`` and ``,``
    slipped through in review); keying on the word sequence closes the class
    rather than the instances.
    """
    return tuple(_WORD_RE.findall(title.casefold()))


_SEED_WORDS_BY_TITLE: dict[tuple[str, ...], tuple[set[str], ...]] = {
    _normalize_seed_title(title): tuple(_content_words(title) | _content_words(body)
                                        for body in bodies)
    for title, bodies in SEEDED_PLACEHOLDER_BODIES.items()
}


#: A fence line: up to three spaces of indent (CommonMark's cap -- four makes
#: an indented code block, not a fence), then a run of three or more backticks
#: or tildes. The run is the fence; what follows it on an opening line is the
#: info string and is ignored.
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def next_fence_state(line: str, fence: "str | None") -> "str | None":
    """The fenced-code state AFTER ``line``: the opening fence run while inside a
    fenced block, else ``None``.

    The one fence grammar for every line-walker in the hook stack that must not
    read markdown inside a code block as structure -- the section splitter below,
    the principle-alias loader in ``_recall``, ``session_start``'s GOAL splitter
    and principles index, and ``post_write_check``'s memory section counter.
    Each used to carry its own toggle (or none): the corpus splitter had none, so
    a ``## `` line inside a fenced example started a new section in the recall
    corpus and in the banner's catalog check; the others flipped on any line
    starting with three backticks, which a tilde fence or a longer closing run
    does not satisfy. ⚠ The cost of fence-awareness: an UNCLOSED fence swallows
    every heading below it, exactly as a CommonMark renderer would -- a stray
    opener in docs/SHARP_EDGES.md silently drops the sections after it from
    /recall. tests/test_recall.py pins every corpus doc balanced for that reason.
    CommonMark's rule, and this one: a block opened by a run of one character is
    closed only by a run of the SAME character at least as long, alone on its
    line. A fence line is never a heading, whichever way it is going.
    """
    m = _FENCE_RE.match(line)
    if not m:
        return fence
    run = m.group(1)
    if fence is None:
        return run
    closes = (run[0] == fence[0] and len(run) >= len(fence)
              and not line[m.end():].strip())
    return None if closes else fence


def iter_doc_sections(text: str) -> "list[tuple[str, str]]":
    """``[(title, body), ...]`` for every ``## `` section in ``text``.

    Fence-aware: a ``## `` line inside a fenced code block is part of the body it
    sits in, not a heading -- a documented example of a heading must not become
    a section of the recall corpus or a "real section" the banner counts. Single
    owner of this split: ``_recall`` reads the corpus through it and
    ``has_real_sections`` reads the catalogs through it, so the two cannot
    disagree about where a section starts.
    """
    sections: list[tuple[str, str]] = []
    title: str | None = None
    body: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        fenced = fence is not None
        fence = next_fence_state(line, fence)
        if not fenced and line.startswith("## "):
            if title is not None:
                sections.append((title, "\n".join(body)))
            title, body = line[3:].strip(), []
        elif title is not None:
            body.append(line)
    if title is not None:
        sections.append((title, "\n".join(body)))
    return sections


def is_seeded_placeholder(title: str, body: str) -> bool:
    """True when this section is STILL the seeded scaffold -- filled in or not.

    Two questions, both derived from the seed the harness itself deployed:

    1. Is this the seeded HEADING, read as its sequence of words -- so case,
       closing ``#``s, any punctuation and wrapping are ignored? A heading that
       says something else is the operator's section, whatever it contains.
    2. Does the body say anything BEYOND the seed body? The distinct content
       units the section adds over the seed's own prose (and its title) are
       counted -- against EVERY body this seed has shipped, because the adopter
       has whichever one ``init`` wrote on their tree; under
       ``SEEDED_NEW_CONTENT_FLOOR`` against any of them it is still the scaffold.
       A non-empty fenced code block (backtick or tilde) is content outright:
       the seed never had one, and the seed's own advice is to write "a
       one-line way to prove you have hit it". Indented code is not special --
       see ``_CODE_BLOCK_RE`` for why -- and counts by its words.

    The previous rule keyed on one sentinel sentence surviving verbatim, and
    failed both ways (DEF-560): title-casing the heading, dropping the
    sentinel's full stop, rewording ``once`` to ``when``, or deleting the
    sentinel while writing nothing all made an untouched scaffold read as a
    real catalog -- the banner then named an empty file and ``/recall`` served
    the placeholder for a footgun question -- while an operator who wrote their
    first edge above the sentinel and forgot to delete it had that edge hidden
    from both. The seeded heading literally invites writing there, so the
    rule has to be content-aware in both directions, and a residual over the
    seed is the one measure that is.
    """
    seed_word_sets = _SEED_WORDS_BY_TITLE.get(_normalize_seed_title(title))
    if seed_word_sets is None:
        return False
    if _CODE_BLOCK_RE.search(body):
        return False
    words = _content_words(body)
    return any(len(words - seed_words) < SEEDED_NEW_CONTENT_FLOOR
               for seed_words in seed_word_sets)


def has_real_sections(path: Path) -> bool:
    """True when ``path`` carries at least one ``## `` section that is not a
    seeded placeholder.

    The honest form of ``.exists()`` for a doc about to be NAMED to the model.
    DERIVES the answer from content rather than declaring which seeds are
    scaffolds -- so a doc that ships full and untouched (``docs/FAILURE_MODES.md``
    is 6k lines and equally pristine on a fresh tree) passes on its own sections.
    Pristineness is the wrong discriminator; content is the right one.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):  # fail-open: ok deliberate -- an unreadable doc has no real sections; the caller's presence check is what speaks
        return False
    if not text.strip():
        return False
    return any(
        not is_seeded_placeholder(title, body)
        for title, body in iter_doc_sections(text)
    )


# ── Safe stdin reading (BOM + UTF-8 sweep) ───────────────────────────────────


class BadStdin(dict):
    """An empty payload that remembers why it is empty. Every existing caller
    treats it as ``{}`` (falsy, ``.get`` works, ``== {}``); a blocking hook
    checks ``isinstance(data, BadStdin)`` and speaks once (``say_once``), so a
    payload the guard could not read is never a silent allow. ``fault`` is the
    failure's class name (``UnicodeDecodeError``, ``JSONDecodeError``,
    ``NotADict``, ``OSError``), never the payload's text. Only a NON-EMPTY
    payload earns one: empty stdin (a hand-run hook, a test, a lone newline)
    is a plain ``{}`` and stays silent."""

    __slots__ = ("fault",)

    def __init__(self, fault: str) -> None:
        super().__init__()
        self.fault = fault


def read_stdin_safely() -> dict:
    """Read a JSON object from stdin; return ``{}`` on any failure -- a
    ``BadStdin`` (an empty dict that remembers the fault) when the payload was
    non-empty and unusable, a plain ``{}`` when it was empty.

    Replaces the per-hook ``try: json.load(sys.stdin) except ...`` pattern.
    Closes two bypass classes:

    1. **BOM-prefixed JSON** — ``\\xef\\xbb\\xbf{...}`` is valid UTF-8
       but invalid JSON prefix. ``json.load`` raises ``JSONDecodeError``,
       the except returns ``{}``, ``tool_name`` is empty, every
       protected-path check misses → hook returns 0 → ALLOW. Fix:
       decode via ``utf-8-sig`` which silently strips a leading BOM.

    2. **UnicodeDecodeError sister-site sweep** — without centralizing
       here, a hook that lacks ``ValueError`` in its except tuple still
       raises on ``\\xff``-only stdin and exits 1 (script bug) → CC
       fail-opens per the hook protocol. Centralizing here closes all 10
       hooks in one site.

    Returns ``{}`` for any failure shape (empty stdin, decode error,
    parse error, non-dict top level). Hooks then proceed with the same
    early-return shape they already use for missing ``tool_name``.
    """
    try:
        raw = sys.stdin.buffer.read()
    except (OSError, ValueError, AttributeError) as exc:
        return BadStdin(type(exc).__name__)
    if not raw or not raw.strip():
        return {}
    try:
        text = raw.decode("utf-8-sig", errors="replace")
    except (UnicodeDecodeError, LookupError) as exc:
        return BadStdin(type(exc).__name__)
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        return BadStdin(type(exc).__name__)
    if not isinstance(data, dict):
        return BadStdin("NotADict")
    return data


def say_bad_stdin(root: Path, hook: str, event_type: str, data: dict) -> None:
    """The blocking hooks' one line for a payload they could not read: once a
    session, with the fault's class name and never the payload's text. A
    no-op for a plain ``{}`` (empty stdin), so a hand-run hook stays quiet."""
    if isinstance(data, BadStdin):
        # One key PER HOOK: a shared key let the first hook to speak silence
        # the other three for the session (the 2-A failure-mode review).
        say_once(
            root, f"bad-stdin-{hook}", hook, event_type,
            f"stdin was not a JSON object ({data.fault}); the payload is read as empty",
            fault=data.fault,
        )


# ── Atomic write ─────────────────────────────────────────────────────────────

#: The lock a torn-able state write writes its BYTES under, process-wide
#: (DEF-1160). ``write_guard`` judges a call in a worker thread and, when its
#: time budget runs out first, ends the process from the main thread with
#: ``os._exit``, which stops the worker wherever it is. An append cut off
#: mid-line leaves a torn record the next append runs into (the audit log, the
#: discard-snapshot log and the reinject telemetry log are read line by line),
#: so each append the guard reaches writes and flushes its line holding this
#: lock -- `tests/test_write_guard_time_budget.py` derives that population and
#: pins it -- and the refusal takes it before it exits: the worker is never
#: stopped inside one. Two kinds need none. An
#: atomic write (``atomic_write_text``: a tempfile, then ``os.replace``) leaves
#: the old file or the new one, and at worst an orphan dot-named tempfile
#: under the state directory. An exists-only flag (the speed-bump one-shot,
#: the reinject once-flag, the maintenance-bypass flag) reads the same whole
#: or cut off. ORDER: take this INSIDE a file lock, never around one -- the
#: refusal writes its own audit record (the file lock, then this) holding
#: nothing, and only then takes this alone, so a writer that waited on a file
#: lock while holding this could deadlock the refusal until the hook's
#: timeout let the call through.
#: A hook with no budget never contends for it; an uncontended acquire costs
#: well under a microsecond.
STATE_WRITE_LOCK = threading.RLock()

#: The monotonic time by which this process's judgment must be done, while a
#: time budget runs it (``write_guard.main`` sets it before its worker starts
#: and clears it once the verdict is out); None otherwise. Read by
#: ``spawn_timeout``.
_judgment_deadline: float | None = None
#: What a spawn leaves the judgment after it under a budget: a git that runs
#: out of time still ends with this much of the budget to finish judging in.
SPAWN_RESERVE_S = 0.5


def set_judgment_deadline(deadline: float | None) -> None:
    """Arm (a monotonic time) or clear (None) the judgment's deadline."""
    global _judgment_deadline
    _judgment_deadline = deadline


def spawn_timeout(default: float) -> float:
    """A spawn's timeout inside a judgment: ``default``, or -- while a time
    budget runs -- the time left before its deadline less ``SPAWN_RESERVE_S``
    when that is shorter, never below 50 ms. A git the guard asks during its
    judgment (a discard snapshot, a dirty-tree check) that runs slow then
    times out into its own fail-open (no snapshot, said once) and the call is
    still judged, instead of the whole call being refused as unjudged."""
    deadline = _judgment_deadline
    if deadline is None:
        return default
    return max(0.05, min(default, deadline - time.monotonic() - SPAWN_RESERVE_S))


# Flags for the writer's per-call tempfile: create-exclusive, never following
# a symlink planted at the random name, binary on Windows so the CRT does not
# translate newlines under the text layer. The POSIX-only flags fall back to
# 0, a no-op OR (docs/SHARP_EDGES.md "POSIX-only os.O_* flags need getattr
# guards for Windows").
_TEMPFILE_OPEN_FLAGS = (
    os.O_RDWR | os.O_CREAT | os.O_EXCL
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_BINARY", 0)
)


#: ``os.replace`` attempts. Windows refuses a rename onto a file another handle
#: holds open -- a reader, or a writer mid-replace -- with ``PermissionError``,
#: so a writer racing one retries there, about a second in all; elsewhere a
#: refusal is real and raises at once. Inlined at the replace (never a helper)
#: so tests/test_atomic_io.py::_REPLACE_WRITERS keeps its roster.
_REPLACE_ATTEMPTS = 20 if sys.platform == "win32" else 1
_REPLACE_BACKOFF_S = 0.005


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Write ``content`` to ``path`` atomically.

    Concurrent readers (other hook subprocesses, parallel Claude Code
    sessions) either see the OLD contents or the NEW contents, never a
    torn / truncated file. The mechanism: write to a per-call tempfile
    in the same directory, then ``os.replace`` onto the target. Same
    directory matters — ``os.replace`` is only atomic within one
    filesystem, and ``os.path.dirname(path)`` is guaranteed to be on the
    same fs as ``path``.

    Direct ``Path.write_text`` on JSON state (cognitive blueprint, integrity
    manifest, fingerprint, harness config) is unsafe: two CC sessions in the
    same repo (e.g., parent + worktree) racing on a finalize/refresh produce
    torn JSON visible to hook readers as ``JSONDecodeError``. Route all such
    writes through this helper.

    Parent directories are created as needed (``mkdir(parents=True)``).
    The tempfile is cleaned up on failure; on success the tempfile no
    longer exists (it was renamed onto ``path``).

    The target's identity survives the write (DEF-783, DEF-784):

    - MODE: an existing regular file keeps the bits it had (the operator's
      ``chmod +x`` on a hook script, ``chmod g+r`` on a settings file); a
      fresh file gets the mode ``open()`` would give under the process
      umask. The helper imposes no mode of its own. (Windows keeps one
      read-only bit and has no ``fchmod``; the mode leg is a no-op there.)
    - SYMLINK: a symlinked state file is REPLACED by a regular file. The
      state under ``cc/``, ``.espalier`` and ``reports/`` is the harness's
      own, the readers of it that refuse a symlink (the plan file's
      ``read_text_nofollow``, the freshness cache's and the statusline's
      ``O_NOFOLLOW`` opens) can read what the write leaves, and no adopter
      manages harness state by dotfiles. The engine's copy
      (``espalier/_atomic_io.py``) does the same by default and takes a
      ``follow_symlinks`` keyword for the adopter's OWN file (a
      dotfiles-managed ``.gitignore`` or ``settings.json``); this copy has
      no such caller and no keyword.
    - HARDLINK: the new bytes are a new inode, so a second name for the old
      one keeps the old bytes. A property of rename-based atomicity, not a
      defect; the harness never hardlinks its own state.

    The tempfile's visible name is capped at 64 chars so it cannot exceed
    Windows MAX_PATH (260) for an unusually long target filename.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Opened with mode 0o666 so the kernel applies the umask -- what open()
    # gives a fresh file -- where tempfile.mkstemp hardcodes 0o600 and every
    # file the harness wrote ended group-unreadable (DEF-783).
    prefix = f".{path.name[:64]}."
    for _attempt in range(100):
        tmp_path = os.path.join(str(path.parent), prefix + os.urandom(4).hex() + ".tmp")
        try:
            fd = os.open(tmp_path, _TEMPFILE_OPEN_FLAGS, 0o666)
            break
        except FileExistsError:
            continue
        except PermissionError:
            # NT raises this, not FileExistsError, when a DIRECTORY bears
            # the chosen name (the case tempfile.mkstemp retries); anything
            # else is a real refusal.
            if os.name == "nt" and os.path.isdir(tmp_path):
                continue
            raise
    else:
        raise FileExistsError(f"no free tempfile name beside {path}")
    f = None
    try:
        if hasattr(os, "fchmod"):
            # An existing regular target keeps its bits; a symlink or other
            # non-regular file at the path is not a mode to copy. A refused
            # fchmod leaves the umask mode rather than failing the write.
            try:
                st = os.stat(path, follow_symlinks=False)
                if stat.S_ISREG(st.st_mode):
                    os.fchmod(fd, stat.S_IMODE(st.st_mode))
            except OSError:
                pass
        # newline="" writes \n verbatim. Default text mode translates \n -> \r\n
        # on Windows, which inflates serialized byte-size (defeating size caps
        # that count \n) and breaks cross-platform byte-parity of hashed JSON
        # state. POSIX is unaffected (os.linesep=\n).
        f = os.fdopen(fd, "w", encoding=encoding, newline="")
        with f:
            f.write(content)
        for attempt in range(_REPLACE_ATTEMPTS):
            try:
                os.replace(tmp_path, path)
                break
            except PermissionError:
                # A refusal that cannot clear -- a directory at the target, a
                # read-only file -- raises at once; only a held handle is waited out.
                if (attempt + 1 >= _REPLACE_ATTEMPTS or os.path.isdir(path)
                        or (os.path.exists(path) and not os.access(path, os.W_OK))):
                    raise
                time.sleep(_REPLACE_BACKOFF_S * (attempt + 1))
    except BaseException:  # noqa: BLE001 -- clean up tempfile on any failure, then re-raise
        # ANY failure (OSError on replace, TypeError on non-str content,
        # UnicodeEncodeError, even KeyboardInterrupt mid-write) must unlink
        # the tempfile so no orphan is left, then re-raise the original error.
        if f is None:
            # fdopen itself raised (an unknown encoding): the fd is still ours.
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ── Session-state counters ───────────────────────────────────────────────────
# STATE_DIR holds per-session FLAGS/COUNTERS that _clean_state_flags clears at
# SessionStart — NOT the whole dir: it also carries deliberately-persistent
# rolling state (session_length_baseline, born_weak_observations.jsonl), which
# is exempt from the clear list on purpose. The
# counter helpers serve write_count (reflect cadence), tool_call_count, and the
# speed-bump session cap — one flocked idiom, many names. Shared here so
# `_speedbump.py` reuses the proven flock primitive instead of forking a
# ~70-line sister-site.
STATE_DIR = ".espalier-state"
COUNTER_FILE = "write_count"

# stop_gate's two hygiene gates each key on ONE relief flag under STATE_DIR, and
# subagent_stop is the ONLY writer: it fires when the named subagent finishes, so
# the flag records that the work HAPPENED (DEF-495: which docs changed; DEF-608:
# which reviewer ran and what it concluded), never that it was asked for.
# stop_gate reads, session_start sweeps. Keyed by the agent's frontmatter name,
# which is what SubagentStop's ``agent_type`` carries. Named HERE so the writer,
# the reader and the sweeper share one literal (the COLD_OPEN_FLAG argument).
DOCS_REFRESHED = "docs_refreshed"
CODE_REVIEWED = "code_reviewed"
RELIEF_FLAGS: dict[str, str] = {
    "docs-maintainer": DOCS_REFRESHED,
    "code-reviewer": CODE_REVIEWED,
}

# The espalier.toml keys that name the adopter's OWN agents whose run relieves
# a gate, beside the shipped one in RELIEF_FLAGS (key -> the flag it relieves).
# A Node or Astro adopter's reviewer is theirs: until 2026-10-06 the only way
# to clear Gate 3 was a reviewer authored for another project, a renamed copy
# of theirs, a hand record, or maintenance mode for the whole session.
# Designating a weak agent opens no new bypass: the hand record and maintenance
# mode already exist, and stop_gate calls Gates 2 and 3 session-hygiene
# friction. ``relief_flags`` is the one reader, for the writer (subagent_stop),
# the reader (stop_gate) and the deny messages alike; the sweeper's flag names
# are these same two values.
RELIEF_AGENT_KEYS: dict[str, str] = {
    "code_review_agents": CODE_REVIEWED,
    "docs_refresh_agents": DOCS_REFRESHED,
}

#: An agent's frontmatter name, which is what SubagentStop's ``agent_type``
#: carries for a project or user agent. Twinned in espalier/config.py, which
#: warns at load so doctor names a bad entry (tests/test_forced_copy_parity.py).
_AGENT_NAME_SHAPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
#: Claude Code's built-in agent types, lower-cased: declaring one would let
#: every general subagent run clear a gate, so the relief reader refuses them.
BUILTIN_AGENT_NAMES: frozenset[str] = frozenset({
    "general-purpose", "explore", "plan", "statusline-setup", "claude-code-guide",
    "output-style-setup",
})


def declared_relief_agents(root: Path, *, hook: str) -> dict[str, str]:
    """The adopter's agents espalier.toml declares under ``RELIEF_AGENT_KEYS``,
    as agent name -> relief flag. A value that is not a list of strings, an
    entry that is not an agent name, a shipped agent's name (already mapped)
    and a name declared for both gates are ignored and SAID once a session
    (``say_once``, from ``hook``). A declared name with no body on disk is
    still honoured -- a user-level or plugin agent reports the same
    ``agent_type`` -- and the deny messages say where no body was found.
    Read on every call. Never raises."""
    def _malformed(text: str) -> None:
        say_once(
            root, "relief-agents-toml", hook, "config_zone_ignored",
            f"espalier.toml could not be parsed ({text}); no declared agent "
            "relieves a stop gate this session",
            setting="relief_agents",
        )

    out: dict[str, str] = {}
    for key, flag in RELIEF_AGENT_KEYS.items():
        # The one hook-side reader, so a hook interpreter with no TOML parser
        # still reads the key through its regex arm.
        raw = read_toml_string_list(root, key, on_error=_malformed)
        if raw is None:
            continue
        if not isinstance(raw, list):
            say_once(
                root, f"relief-agents-{key}-not-a-list", hook, "config_zone_ignored",
                f"espalier.toml: {key} must be a list of agent names, got "
                f"{type(raw).__name__}; it relieves nothing",
                setting=key,
            )
            continue
        for i, entry in enumerate(raw):
            name = entry.strip() if isinstance(entry, str) else ""
            if not _AGENT_NAME_SHAPE.match(name):
                why = "is not an agent name"
            elif name.lower() in BUILTIN_AGENT_NAMES:
                why = "is a built-in agent, and any run of it would clear the gate"
            elif name in RELIEF_FLAGS:
                why = "is a shipped agent the relief table already maps"
            elif out.get(name, flag) != flag:
                why = "is declared for both stop gates; the first declaration stands"
            else:
                out[name] = flag
                continue
            say_once(
                root, f"relief-agents-{key}-{i}", hook, "config_zone_ignored",
                f"espalier.toml: {key} entry {entry!r} {why}; ignored",
                setting=key,
            )
    return out


def relief_flags(root: Path, *, hook: str) -> dict[str, str]:
    """Agent name -> the relief flag its run writes: the shipped table plus
    the adopter's declared agents (``declared_relief_agents``)."""
    return {**RELIEF_FLAGS, **declared_relief_agents(root, hook=hook)}


def relief_agents_line(root: Path, flag: str, *, hook: str) -> str:
    """One line for a stop gate's deny message naming the adopter's declared
    agents that relieve ``flag`` (empty when none is declared), each marked
    where no body was found under ``.claude/agents/`` or ``~/.claude/agents/``
    so a misspelled name is visible at the moment it costs something."""
    names = [n for n, f in declared_relief_agents(root, hook=hook).items() if f == flag]
    if not names:
        return ""
    key = next((k for k, f in RELIEF_AGENT_KEYS.items() if f == flag), "the relief keys")
    rendered = []
    for name in names:
        bodies = (root / ".claude" / "agents" / f"{name}.md", Path.home() / ".claude" / "agents" / f"{name}.md")
        try:
            found = any(p.is_file() for p in bodies)
        except (OSError, RuntimeError):  # fail-open: ok deliberate -- an unreadable home or tree: the name is shown unmarked
            found = True
        rendered.append(f"`{name}`" + ("" if found else " (no body found under .claude/agents/)"))
    return (
        f"\n  This repository also accepts its own agent here (espalier.toml {key}): "
        + ", ".join(rendered) + " -- dispatch it by that name."
    )
# The one hand-written relief record both gates honour: ``agent`` is this value
# and ``note`` says why. A judgement the operator is recording, not a gate being
# skipped -- the deny messages name it, stop_gate announces its use on stderr
# (the debug log, like a maintenance-mode bypass -- stop_gate exits 0, and that
# stderr never reaches the transcript), and a note shorter than the floor is a
# word, not a judgement.
OPERATOR_RELIEF_AGENT = "operator"
OPERATOR_RELIEF_NOTE_MIN_CHARS = 20

# Cold-open baton flag. SessionStart (producer) drops it on a new-session source;
# task_router (consumer) reads-and-deletes it on the session's first prompt to
# enforce an un-preemptible orientation readout. Named HERE — the one module both
# standalone hooks already import — so the producer and consumer can never drift on
# the literal (the parity problem, avoided by sharing instead of duplicating).
COLD_OPEN_FLAG = "cold_open_pending"

# Per-session markers. Three hooks share these: session_start
# WRITES one marker per session under STATE_DIR/SESSIONS_DIR, named by the
# payload's session_id, and READS the siblings to name another live session in
# the same tree (the banner's `Sessions:` line); task_router TOUCHES this
# session's marker on every prompt -- the heartbeat the reader's live window
# measures -- and hands it the hook's parent pid, so a marker the heartbeat has
# to write itself, or one an earlier build wrote with no pid, carries the
# window's identity a `clear` retires by. A directory, not a flag file, so _clean_state_flags' named list and
# prefix globs never reach it: the OTHER session's marker must survive this
# session's start, or the second start erases the evidence of the first (the
# clobber the line exists to name). Pruned by age only. Same producer/consumer
# parity argument as COLD_OPEN_FLAG above: one literal, three readers.
SESSIONS_DIR = "sessions"
SESSION_MARKER_LIVE_S = 4 * 3600       # touched within this window: named as live
SESSION_MARKER_PRUNE_S = 7 * 86400     # untouched for this long: swept at SessionStart
SESSION_ID_MAX_CHARS = 64
#: Each session's zone baseline (``_zone_watch``) and the lock
#: beside it sit next to the session's marker, under the marker's stem, with a
#: suffix the marker readers' ``*.json`` glob never matches. A file a session
#: owns has one lifetime: the marker's two sweeps below retire them with it.
ZONE_BASELINE_SUFFIX = ".zones"
SESSION_SIDE_SUFFIXES = (ZONE_BASELINE_SUFFIX, ZONE_BASELINE_SUFFIX + ".lock")
_SESSION_ID_UNSAFE_RE = re.compile(r"[^A-Za-z0-9_-]")
_SESSION_MARKER_CWD_MAX_CHARS = 120    # keeps the record under the flag-parity pin's 1 KiB


def safe_session_id(sid: object) -> str:
    """The payload's ``session_id`` as a file name: untrusted text, so anything
    outside ``[A-Za-z0-9_-]`` is dropped and the rest capped at
    SESSION_ID_MAX_CHARS. '' when nothing survives -- and a '' id writes,
    touches and reads nothing (a payload with no id has no marker)."""
    if not isinstance(sid, str):
        return ""
    return _SESSION_ID_UNSAFE_RE.sub("", sid)[:SESSION_ID_MAX_CHARS]


def sessions_dir(root: Path) -> Path:
    """Where the per-session markers live under ``root``."""
    return root / STATE_DIR / SESSIONS_DIR


def session_marker_path(root: Path, sid: object) -> Path | None:
    """``sid``'s marker path, or None for an id nothing survives of."""
    safe = safe_session_id(sid)
    if not safe:
        return None
    return sessions_dir(root) / f"{safe}.json"


def _read_marker(path: Path) -> dict[str, Any]:
    """A marker's JSON object, or {} when there is no readable one (the mtime
    is the fact that counts a marker; its JSON is a courtesy)."""
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # fail-open: ok deliberate -- an unreadable marker still counts by its mtime
        return {}
    return record if isinstance(record, dict) else {}


def _marker_started(path: Path) -> str | None:
    """The ``started`` stamp a marker on disk carries ('' when it recorded an
    unknown start); None when there is no readable marker."""
    started = _read_marker(path).get("started")
    return started if isinstance(started, str) else None


def _tail_capped(text: str, limit: int) -> str:
    """The LAST ``limit`` characters, marked: a path's leaf is what tells two
    checkouts apart, and a head cut yields a plausible-looking wrong path."""
    return text if len(text) <= limit else "..." + text[-(limit - 3):]


def write_session_marker(
    root: Path, sid: object, *, pid: int | None = None, cwd: str = "",
    source: str = "", started: str | None = None, keep_started: bool = False,
) -> bool:
    """Write (or rewrite) ``sid``'s marker: a small JSON object -- the id, when
    it started (ISO UTC; ``started=None`` means now, ``''`` means unknown, as
    the heartbeat's self-heal writes it), the window's pid (``window_pid``:
    the Claude Code process the hook runs under, which is what a ``clear``
    uses to retire the predecessor's marker; never a liveness
    oracle; anything but a positive int is recorded as None, the one rule
    ``_window_pid`` holds for every reader), the payload's ``cwd`` (tail-capped, so the leaf that tells two
    checkouts apart survives) and ``source``. ``keep_started`` carries the stamp a
    prior marker holds forward -- a mid-session ``compact`` or ``resume``
    re-fires SessionStart, and the session did not start again. Atomic; never
    raises -- a read-only or full state dir costs the marker, never the hook.
    Returns whether it landed."""
    path = session_marker_path(root, sid)
    if path is None:
        return False
    if started is None and keep_started:
        started = _marker_started(path)
    if started is None:
        started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    record = {
        "session_id": safe_session_id(sid),
        "started": started,
        "pid": _window_pid(pid),
        "cwd": _tail_capped(cwd, _SESSION_MARKER_CWD_MAX_CHARS) if isinstance(cwd, str) else "",
        "source": source[:32] if isinstance(source, str) else "",
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, json.dumps(record, ensure_ascii=True) + "\n")
        return True
    except OSError:  # fail-open: ok deliberate -- a marker that cannot be written costs the Sessions: line, never the hook
        return False


def _window_pid(pid: object) -> int | None:
    """``pid`` as a window identity: a positive int, or None for anything else
    (a bool is an int to Python and never a pid)."""
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return None
    return pid


def load_checkout_sync() -> Any:
    """``tools/cc/checkout_sync.py`` by path under a private alias, once per
    process: SessionStart's catch-up and reaper, and the window key below. None
    where it is not deployed beside the hooks (an older deploy set costs those
    lines, never the hook)."""
    path = Path(__file__).resolve().parent.parent / "checkout_sync.py"
    if not path.is_file():
        return None
    alias = "_hooks_checkout_sync"
    mod = sys.modules.get(alias)
    if mod is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location(alias, path)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[alias] = mod  # before exec: its dataclasses resolve the module by name
        spec.loader.exec_module(mod)
    return mod


def window_pid() -> int:
    """The window's pid for the session markers: the Claude Code process this
    hook runs under (``checkout_sync.window_pid``: the hook's parent, or on
    Windows the parent of the venv launcher between them), else the hook's
    parent, the key a deploy without ``checkout_sync.py`` had. Never raises."""
    try:
        sync = load_checkout_sync()
        pid = sync.window_pid() if sync is not None else None
    except Exception:  # noqa: BLE001  # fail-open: ok deliberate -- a registry or process table that cannot be read keeps the hook's parent, the key before the registry read
        pid = None
    return _window_pid(pid) or os.getppid()


def touch_session_marker(root: Path, sid: object, *, pid: object = None, cwd: str = "") -> bool:
    """The heartbeat: bump the marker's mtime. A marker that is missing (a
    session that started before this landed, or one the prune swept) is written
    with an unknown start time, so a live session is never read as absent for
    want of its start -- and with the window's ``pid`` and the payload's
    ``cwd`` (``source`` ``heartbeat``), so a ``clear`` in the same window can
    retire it. A marker on disk that records NO pid (the stub an earlier
    build's heartbeat wrote, or one that does not parse) is rewritten once with
    the pid, keeping the start, cwd and source it holds; a pid it already
    records is never overwritten (the SessionStart write is the authority), and
    a touch with no pid of its own repairs nothing. ``pid`` may be a
    zero-argument callable (``window_pid``), called only when the marker is
    written or repaired: the window key can read the process table, which a
    prompt's heartbeat should not pay for on every prompt. Never raises."""
    path = session_marker_path(root, sid)
    if path is None:
        return False

    def window() -> int | None:
        return _window_pid(pid() if callable(pid) else pid)

    try:
        os.utime(path, None)
    except FileNotFoundError:
        return write_session_marker(root, sid, pid=window(), cwd=cwd, source="heartbeat", started="")
    except OSError:  # fail-open: ok deliberate -- a heartbeat that cannot land costs the live window, never the prompt
        return False
    record = _read_marker(path)
    if _window_pid(record.get("pid")) is not None:
        return True
    key = window()   # read only now, when the record needs it
    if key is None:
        return True
    # Repair, once: the heartbeat landed, so the return is the touch's, and a
    # rewrite that cannot land is the writer's own declared fail-open. This is
    # the one read-modify-write on a marker (Core Rule 14): a SessionStart
    # write for a compact or resume landing between the read and the rewrite
    # keeps the start it read from this same stub and the same pid, so the
    # loser's record differs in ``source`` alone, which no reader consumes.
    held_cwd = record.get("cwd") if isinstance(record.get("cwd"), str) else ""
    held_source = record.get("source") if isinstance(record.get("source"), str) else ""
    held_started = record.get("started") if isinstance(record.get("started"), str) else ""
    write_session_marker(root, sid, pid=key, cwd=held_cwd or cwd,
                         source=held_source or "heartbeat", started=held_started)
    return True


def _retire_session_side_files(directory: Path, stem: str) -> None:
    """Remove the files a session keeps beside its marker. Never raises: a
    file a sibling removed first, or a lock another process holds open (which
    Windows refuses to delete), stays for the next sweep."""
    for suffix in SESSION_SIDE_SUFFIXES:
        try:
            (directory / f"{stem}{suffix}").unlink(missing_ok=True)
        except OSError:  # fail-open: ok deliberate -- removed by a sibling first, or a lock still held open; the next sweep takes it
            continue


def prune_session_markers(root: Path, now: float | None = None) -> int:
    """Delete the markers untouched for SESSION_MARKER_PRUNE_S, with the files
    each session keeps beside its marker, and any such file whose marker is
    gone once it too is that old. Returns the count of markers swept; never
    raises (a sibling session may sweep the same file first)."""
    now = time.time() if now is None else now
    directory = sessions_dir(root)
    try:
        entries = list(directory.iterdir())
    except OSError:  # fail-open: ok deliberate -- an unreadable state dir sweeps nothing
        return 0
    stems = {p.stem for p in entries if p.suffix == ".json"}
    swept = 0
    for path in entries:
        name = path.name
        try:
            if name.endswith(".json"):
                if now - path.stat().st_mtime > SESSION_MARKER_PRUNE_S:
                    path.unlink(missing_ok=True)
                    _retire_session_side_files(directory, path.stem)
                    swept += 1
                continue
            stem = next((name[: -len(s)] for s in SESSION_SIDE_SUFFIXES if name.endswith(s)), None)
            if stem is not None and stem not in stems and now - path.stat().st_mtime > SESSION_MARKER_PRUNE_S:
                path.unlink(missing_ok=True)
        except OSError:  # fail-open: ok deliberate -- a marker a sibling swept first, or one that cannot be read
            continue
    return swept


def _marker_time_s(stamp: str) -> float | None:
    """A marker's ISO ``started`` as epoch seconds; None when it does not parse
    (a naive stamp reads as UTC)."""
    try:
        parsed = datetime.fromisoformat(stamp)
    except ValueError:  # fail-open: ok deliberate -- an unparseable start reads as unknown; the mtime still counts the marker
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def other_live_sessions(root: Path, sid: object, now: float | None = None) -> list[dict[str, Any]]:
    """The sibling markers touched within SESSION_MARKER_LIVE_S, most recently
    touched first: ``session_id``, ``started`` ('' when unreadable -- the mtime
    is the fact that counts a marker; its JSON is a courtesy), ``last_seen_s``
    and ``started_s`` (ages in seconds; ``started_s`` None when unknown),
    ``cwd`` and ``pid`` as recorded ('' / None when unreadable). This
    session's own marker, by ``sid``, is left out. Never raises."""
    now = time.time() if now is None else now
    own = safe_session_id(sid)
    rows: list[dict[str, Any]] = []
    try:
        entries = list(sessions_dir(root).glob("*.json"))
    except OSError:  # fail-open: ok deliberate -- an unreadable state dir names nobody
        return rows
    for path in entries:
        if own and path.stem == own:
            continue
        try:
            # A marker from the future (clock skew) is live, not absent.
            age = max(0.0, now - path.stat().st_mtime)
        except OSError:  # fail-open: ok deliberate -- a marker a sibling swept between the glob and the stat
            continue
        if age > SESSION_MARKER_LIVE_S:
            continue
        record = _read_marker(path)
        started = record.get("started") if isinstance(record.get("started"), str) else ""
        started_at = _marker_time_s(started) if started else None
        cwd = record.get("cwd") if isinstance(record.get("cwd"), str) else ""
        pid = record.get("pid") if isinstance(record.get("pid"), int) else None
        rows.append({
            "session_id": path.stem,
            "started": started,
            "last_seen_s": age,
            "started_s": max(0.0, now - started_at) if started_at is not None else None,
            "cwd": cwd,
            "pid": pid,
        })
    rows.sort(key=lambda row: row["last_seen_s"])
    return rows


def retire_same_window_markers(root: Path, sid: object, pid: object) -> list[str]:
    """On a ``clear`` the previous session in THIS window is gone, and its
    marker, touched minutes ago, would read as a live sibling for hours (a
    clear mints a new session id: measured 2026-10-05, the transcript stem
    changed across one). The window's pid (``window_pid``: the Claude Code
    process, which a clear keeps) is its identity across the clear: every
    sibling marker recording this ``pid`` is the predecessor's and is removed.
    Where no key was found (an unregistered parent that is no launcher, or a
    marker an older build wrote) the recorded number is a dead process's and
    nothing matches, so the line may name the predecessor; the one way a live
    sibling's marker is lost is a recycled number landing on a dead one's --
    the pid is a window identity, never a liveness oracle. The own marker, by
    ``sid``, is never touched.
    Returns the stems removed. Never raises."""
    window = _window_pid(pid)
    if window is None:
        return []
    own = safe_session_id(sid)
    removed: list[str] = []
    try:
        entries = list(sessions_dir(root).glob("*.json"))
    except OSError:  # fail-open: ok deliberate -- an unreadable state dir retires nothing
        return removed
    for path in entries:
        if own and path.stem == own:
            continue
        if _read_marker(path).get("pid") != window:
            continue
        try:
            path.unlink(missing_ok=True)
            removed.append(path.stem)
        except OSError:  # fail-open: ok deliberate -- a marker a sibling swept first
            continue
        _retire_session_side_files(path.parent, path.stem)
    return removed

# Recall-engine telemetry log. Named HERE because BOTH writers import it --
# _reinject._log_recall_event on the push side, the _recall.py CLI shim on the
# pull side -- the same producer/consumer parity argument as COLD_OPEN_FLAG above.
# The name must NOT begin with `reinject_`: session_start._clean_state_flags globs
# that prefix at every non-continuation SessionStart and would erase this
# cross-session history, presenting as "telemetry isn't working" rather than
# "telemetry is being erased".
RECALL_LOG_NAME = "recall_events.jsonl"

# Opt-in escape hatch for the tests that exercise the telemetry path itself.
# Everything else in the suite is suppressed -- see _telemetry_enabled.
TELEMETRY_TEST_OPT_IN = "ESPALIER_TELEMETRY_UNDER_TEST"


def _read_counter(
    state_dir: Path, name: str = COUNTER_FILE, *,
    hook: str = "reflect_trigger", event_type: str = "posttooluse_failed_open_counter",
) -> int:
    """Read the named counter (defaults to ``write_count``). The ``name`` param
    lets the same reader serve ``tool_call_count`` too."""
    counter_path = state_dir / name
    if not counter_path.exists():
        return 0
    try:
        return int(counter_path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError) as exc:
        # Fail open, with voice: a counter that reads as zero restarts the
        # cadence it drives (the reflect trigger, the stop gate's thresholds).
        say_once(
            state_dir.parent, f"counter-read-{name}", hook, event_type,
            f"{name} could not be read ({type(exc).__name__}); its cadence restarts from zero this session",
            fault=type(exc).__name__, counter=name,
        )
        return 0


def _write_counter(state_dir: Path, count: int, name: str = COUNTER_FILE) -> None:
    """Write the named counter atomically (temp + os.replace in the same dir).

    Route through ``atomic_write_text`` so the unlocked reader
    (``stop_gate._read_write_count`` / our own ``_read_counter``) never catches
    an empty-file truncate window — reading 0 and resetting the every-10th-write
    cadence. Same-dir replace keeps the swap on one filesystem. The ``name``
    param's back-compat default keeps every existing ``write_count`` caller
    unchanged.
    """
    state_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(state_dir / name, str(count))


def _locked_increment(
    state_dir: Path, name: str = COUNTER_FILE, *,
    hook: str = "reflect_trigger", event_type: str = "posttooluse_failed_open_counter",
) -> int:
    """Atomically read-modify-write the counter.

    A naive ``count = _read_counter() + 1; _write_counter(count)`` is a
    classic TOCTOU: two parallel CC sessions both read N, both write
    N+1, the counter drifts by half. The reflect-every-10th-write
    cadence depends on the counter being monotonic across sessions,
    so the drift breaks the trigger semantics for users running CC in
    a parent repo + worktree simultaneously.

    Mechanism: :func:`lock_file` -- ``flock`` on POSIX, ``LockFileEx`` on
    Windows -- gives exclusion across processes on a stable sibling lock
    file. Windows ran this read-modify-write unlocked until 2026-10-02, on the
    premise that its operators rarely run two sessions in one repo; parallel
    hooks in ONE session are concurrent writers too, and eight of them left the
    counter at 14 of 200 increments (``tests/test_reflect_trigger_concurrency.py``).

    Returns the new count after increment.

    A read-only ``state_dir`` (``mkdir`` / ``write`` raises) or a flock-less
    POSIX FS (``flock`` raises ``OSError`` — some NFS / network mounts) would
    otherwise propagate an uncaught ``OSError`` and crash this PostToolUse hook
    with exit 1 — a fail-open of the entire event. We degrade to a best-effort
    read (no increment) so the hook stays alive on such hosts; the cadence
    counter simply doesn't advance while the dir is unwritable. (Sister-site of
    ``cognitive_blueprint._acquire_write_lock``.)
    """
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        # Read-only state dir -- can't persist; degrade to best-effort read of
        # THE SAME counter (``name`` was dropped here until 2026-09-30, so a
        # caller counting anything but the default file read the default's
        # count), and say so once: the cadence this counter drives stops
        # advancing while the dir is unwritable.
        say_once(
            state_dir.parent, f"counter-{name}", hook, event_type,
            f"{name} cannot be written ({type(exc).__name__}); the count stands still this session",
            fault=type(exc).__name__, counter=name,
        )
        return _read_counter(state_dir, name, hook=hook, event_type=event_type)
    # Serialize the read-modify-write across processes on a STABLE
    # sibling lock file (never replaced), then write the counter ATOMICALLY
    # via _write_counter (temp + os.replace). The unlocked reader
    # (stop_gate._read_write_count) takes no LOCK_SH, so an in-place
    # seek/truncate/write would expose an empty-file window the reader could catch —
    # reading 0 and resetting the every-10th-write cadence, skipping Gates 2/3.
    # Locking the counter's OWN fd is incompatible with atomic replace:
    # os.replace swaps the inode out from under the lock, so a second writer
    # could re-read the stale pre-replace value and drop an increment. Mirrors
    # cognitive_blueprint._acquire_write_lock — lock a sibling, write atomically.
    lock_path = state_dir / (name + ".lock")
    try:
        lock_fh = open(lock_path, "a+", encoding="utf-8")
    except OSError:
        # An unwritable lock file: the counter beside it is unwritable too, so
        # degrade to a best-effort read, no crash.
        return _read_counter(state_dir, name)
    try:
        try:
            lock_file(lock_fh)
        except OSError:
            # The lock call itself refused: a filesystem that cannot lock (some
            # NFS / network mounts), or a `_json_safe.py` that predates the
            # primitive on Windows. Increment UNLOCKED, as _speedbump's degrade
            # does -- a read-only answer here froze the counter for good, and with
            # it the reflect cadence, silently (failure-mode review, 2026-10-02).
            current = _read_counter(state_dir, name)
            try:
                _write_counter(state_dir, current + 1, name)
            except OSError:
                return current
            return current + 1
        try:
            current = _read_counter(state_dir, name)
            new = current + 1
            _write_counter(state_dir, new, name)
        except OSError:
            # The write failed under the lock (a full disk, a now-unwritable
            # file): degrade to a best-effort read, no crash.
            return _read_counter(state_dir, name)
        finally:
            try:
                unlock_file(lock_fh)
            except OSError:  # fail-open: ok deliberate -- closing the handle below releases the lock; the count is already written
                pass
        return new
    finally:
        lock_fh.close()


def _session_marker(state_dir: Path) -> str:
    """The current session's start stamp — the key that groups telemetry by session.

    ``session_started`` is rewritten at every SessionStart
    (``session_start._clean_state_flags``), so its contents are a stable
    per-session key that costs nothing to produce. Returns ``""`` when absent (a
    hook firing before the first SessionStart, or a tmp_path under test).
    """
    try:
        marker = state_dir / "session_started"
        return marker.read_text(encoding="utf-8", errors="replace").strip()[:64]
    except (OSError, ValueError):  # fail-open: ok telemetry -- the per-session grouping key of the born-weak observations; no key, no grouping
        return ""


def _telemetry_enabled(root: Path) -> bool:
    """True when recall-engine telemetry should be recorded for ``root``.

    Two gates, both deliberately quiet:

    * **A pytest run is not an operator session.** The suite drives these hooks
      hundreds of times per run, and every one of those drives would otherwise
      append to the LIVE log. Measured on day one: 89% of rows were suite
      artifacts, which is enough to invert the conclusion a reader draws from
      them. ``conftest``'s autouse live-tree write guard deliberately does NOT
      watch ``STATE_DIR`` (the operator's own hooks churn it on every tool call),
      so this lands in a known blind spot where nothing else would catch it.
      Tests that exercise telemetry set ``TELEMETRY_TEST_OPT_IN``.
    * **Self-host only.** Mirrors the born-weak observation log, which is
      self-host-gated for the same reason: the pull side records the operator's
      raw ``/recall`` query text, and capturing an adopter's prompts — even to a
      gitignored local file — is a consent question the harness does not open
      unasked.
    """
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get(TELEMETRY_TEST_OPT_IN):
        return False
    return is_self_host_repo(root)


def _append_jsonl(state_dir: Path, name: str, record: dict) -> None:
    """Best-effort append of one JSON record to ``state_dir/name``.

    Generalizes the append idiom already proven in
    ``_born_weak.bw_log_observation`` rather than forking a weaker sister-site:
    the write is serialized under :func:`lock_file` on a STABLE sibling lock
    file (mirroring ``_locked_increment`` above). Two concurrent hooks — parallel
    tool calls in one session, or a parent repo and a git worktree sharing one
    ``.espalier-state`` — could otherwise interleave one record into a malformed
    JSONL line, or on Windows lose it outright.

    Telemetry is NEVER load-bearing: a read-only state dir, a full disk, or a
    flock-less FS must not crash a reporter hook. Every failure is swallowed —
    the cost of a lost telemetry line is a gap in a graph, and the cost of an
    uncaught OSError here is a fail-open of the whole hook event. That outer
    swallow is the one deliberate divergence from ``bw_log_observation``, which
    lets a mid-write OSError propagate once into its caller's umbrella.
    """
    try:
        from datetime import datetime, timezone  # deferred: this module is re-imported per tool call

        state_dir.mkdir(parents=True, exist_ok=True)
        stamped = dict(record)
        # `ts` mirrors bw_log_observation (which stamps every one of its rows);
        # `session` is what makes the log analyzable at all. The ceilings this
        # instrument exists to evaluate are PER-SESSION quantities, so rows that
        # cannot be grouped into sessions cannot answer the question -- and a
        # cross-session pile of byte-identical rows carrying only a count would
        # answer it CONFIDENTLY WRONG, which is worse than not answering.
        stamped.setdefault("ts", datetime.now(timezone.utc).isoformat())
        stamped.setdefault("session", _session_marker(state_dir))
        line = json.dumps(stamped, ensure_ascii=True, sort_keys=True) + "\n"
        log_path = state_dir / name

        def _append() -> None:
            # The line goes out whole under STATE_WRITE_LOCK (inside the file
            # lock below): write_guard's budget refusal ends the process only
            # between lines, never inside one (its reinject telemetry lands here).
            with STATE_WRITE_LOCK, log_path.open("a", encoding="utf-8") as fh:
                fh.write(line)

        # Acquire the lock in its OWN try so the unlocked fallback fires ONLY when
        # lock acquisition fails (flock-less FS / unwritable lock / a lock Windows
        # refused) — never as a retry of a mid-write append, which would
        # double-append a torn record. Windows locks too since 2026-10-02: an
        # unlocked append there lost lines under eight concurrent writers
        # (tests/test_file_lock.py).
        lock_fh = None
        try:
            lock_fh = open(state_dir / (name + ".lock"), "a+", encoding="utf-8")
            lock_file(lock_fh)
        except OSError:  # fail-open: ok deliberate -- a filesystem that cannot lock: the unlocked append is the documented limit and the line still lands
            if lock_fh is not None:
                lock_fh.close()
            _append()
            return
        try:
            _append()
        finally:
            try:
                unlock_file(lock_fh)
            finally:
                lock_fh.close()
    except Exception:  # noqa: BLE001, S110 -- telemetry never breaks a hook
        pass


# ── Path normalization ───────────────────────────────────────────────────────


def normalize_path(file_path: object, root: Path) -> str:
    """Normalize a file path to be relative to project root.

    Resolves `..` traversals so e.g. `safe_dir/../tools/cc/hooks/x.py`
    canonicalizes to `tools/cc/hooks/x.py` and matches protected
    prefixes. Without this, an agent could bypass `_is_protected` by
    prefixing any protected path with `<unprotected>/../`.

    Expands ``~`` first so ``~/repo/tools/cc/hooks/x.py`` doesn't
    fall through to the fallback branch (which would return the raw
    string and skip the prefix check).

    Strips a literal ``$CLAUDE_PROJECT_DIR/`` or ``${CLAUDE_PROJECT_DIR}/``
    prefix here too (and PowerShell's ``$env:`` spellings, DEF-716) -- Write
    tool_input paths don't go through ``normalize_bash_path`` and would
    otherwise bypass the protected-zone check by carrying the env-var form
    verbatim.

    Defense-in-depth type-guard for non-str payloads. Callers
    (`check_write_edit`, MCP candidate loop) type-check first; this
    sentinel keeps `_is_protected("<invalid>")` False so the hook's
    `main()` BaseException umbrella catches anything that slips past.

    Single source of truth for path normalization across write_guard,
    plan_guard, reflect_trigger, post_write_check, and any future hook.

    Relative to the CHECKOUT that contains the path, which is not always the
    root (DEF-743): a registered git worktree of the same repository -- nested
    under the root as ``.claude/worktrees/<name>``, or beside it -- is a
    checkout too, and a target inside it reads ``tools/cc/x.py``, never the
    unprotected, plan-exempt ``.claude/worktrees/<name>/tools/cc/x.py``.
    ``resolve_in_checkout`` is the owner; it also returns the checkout, for
    the sites that rejoin the relative path to a directory afterwards.

    The env-var strip is the chokepoint two bypass spellings exploited.
    ``replace("\\", "/")`` runs at the TOP so the ``$CLAUDE_PROJECT_DIR/``
    prefix match and downstream comparison are separator-agnostic (closes the
    backslash sibling); a ``lstrip("/")`` after EACH strip collapses the
    residual leading slash a doubled separator leaves (``$CLAUDE_PROJECT_DIR//x``)
    so it stays repo-relative instead of reading as absolute and falling through
    to the raw-string fallback that misses the protected prefix. The
    trailing-dot/space + NTFS-ADS spelling equivalences are canonicalised at the
    comparison site (`_protected_zones._fs_equiv`), not here, so this function
    stays a faithful relativiser (a POSIX file literally named ``foo.`` is a
    distinct file and must not collapse to ``foo`` outside the protected-zone
    equivalence check).
    """
    return resolve_in_checkout(file_path, root)[1]


#: The repo root as PowerShell spells an environment variable, LOWER-CASED for
#: a case-insensitive prefix compare (DEF-716) -- an entry added in mixed case
#: never matches, and ``tests/test_write_guard.py`` pins the lower-case
#: invariant. ``$env:NAME`` and ``${env:NAME}`` are the natural transcription
#: of the ``${CLAUDE_PROJECT_DIR}`` Claude Code writes into every hook entry;
#: ``$($env:NAME)`` is the idiom for the same variable inside a double-quoted
#: path (both reviews drove it ALLOWING beside the two folded forms). The
#: backslash spelling needs no entry of its own because the separator canon
#: has already folded it. The three strips that parse ``.claude/settings.json``
#: hook entries (``ci_guard``, ``surface_contract``, ``artifact_parity``) read
#: the ``${CLAUDE_PROJECT_DIR}`` exec form ``init`` writes, not an agent's
#: path, and stay deliberately separate from this chokepoint.
_PS_ENV_PROJECT_DIR_PREFIXES = (
    "$env:claude_project_dir/",
    "${env:claude_project_dir}/",
    "$($env:claude_project_dir)/",
    "$(${env:claude_project_dir})/",
)

#: Git Bash (MSYS2) spells a drive as a one-letter first component --
#: ``/c/<home>`` is ``C:\<home>`` -- and that is what the Bash tool's own
#: ``pwd`` returns on Windows, so any path an agent builds from ``pwd``, ``$PWD``
#: or a parent-directory move arrives in it. Neither ``pathlib`` nor ``ntpath``
#: knows the spelling: to them a rooted, drive-less path is not absolute, so
#: joining it onto a drive root fabricates ``C:/c/<home>`` and every compare
#: against the drive-spelled home or repo root misses (DEF-731, walk 2 finding
#: 11: the home directory fell to the clearable delete tier, and a protected
#: write in the same spelling matched no zone). Anchored, one letter, then a
#: separator or the end -- ``/cygdrive/c``, ``/tmp`` and ``//server/share`` do
#: not match. No quantifier, so nothing to backtrack.
_MSYS_DRIVE_RE = re.compile(r"^/([A-Za-z])(?=/|$)")

#: The Windows prefix spellings of a drive path, folded before the MSYS step
#: (DEF-935; walk 4 measured nine of eleven passing every hook on the host):
#: the extended-length and device namespaces, `\\?\C:\x` / `\\.\C:\x`, which
#: long-path presentation and some tools put on a plain drive path; the
#: extended-length UNC form, `\\?\UNC\server\share\x`, which is
#: `\\server\share\x`; and the loopback administrative shares,
#: `\\localhost\C$\x` / `\\127.0.0.1\C$\x`, which open `C:\x` on the machine
#: itself. Each is read in its native spelling or after separator canon
#: (`[\\/]`), anchored, with no quantifier beside another, and a drive letter
#: upper-cased like the MSYS translation's. Unconditional: none of these
#: spells a path on a POSIX host, so folding them there changes no verdict,
#: and the chokepoint-shape pins run on the POSIX dev host.
_WIN_EXTENDED_UNC_RE = re.compile(r"^[\\/]{2}[?.][\\/]UNC[\\/]", re.IGNORECASE)
_WIN_EXTENDED_DRIVE_RE = re.compile(r"^[\\/]{2}[?.][\\/]([A-Za-z]):(?=[\\/]|$)")
_WIN_LOOPBACK_ADMIN_SHARE_RE = re.compile(
    r"^[\\/]{2}(?:localhost|127\.0\.0\.1)[\\/]([A-Za-z])\$(?=[\\/]|$)", re.IGNORECASE)


def _windows_prefixes_to_drive(path: str) -> str:
    """``\\\\?\\C:\\x``, ``\\\\.\\C:\\x``, ``\\\\?\\UNC\\localhost\\C$\\x`` and
    ``\\\\localhost\\C$\\x`` -> ``C:/x`` (``C:/``, the drive ROOT, for a bare
    drive, as the MSYS rule); ``\\\\?\\UNC\\server\\share\\x`` ->
    ``//server/share/x``. Anything else byte-identical -- including a share
    that is not a loopback administrative share (``\\\\localhost\\Public\\x``,
    ``\\\\server\\share\\x``), which nothing static maps to a local path: the
    declared residual of the protected-zone spelling-equivalence write-up.
    """
    folded = False
    match = _WIN_EXTENDED_UNC_RE.match(path)
    if match is not None:
        path, folded = "//" + path[match.end():], True
    match = _WIN_EXTENDED_DRIVE_RE.match(path) or _WIN_LOOPBACK_ADMIN_SHARE_RE.match(path)
    if match is not None:
        path, folded = match.group(1).upper() + ":/" + path[match.end():].lstrip("\\/"), True
    # A folded spelling comes back in ONE separator, whole: the root side
    # (`_project_root_spelling`) folds nothing after this call, and a chokepoint
    # that hands back `C:/repo\\sub` makes every caller fold again (the
    # code review of the fold found the root-side test compensating for it).
    return path.replace("\\", "/") if folded else path


def _msys_drive_to_windows(path: str) -> str:
    """Translate a drive spelling to its Windows form: the Git Bash prefix on
    Windows only; the Windows prefix spellings on every host (the fold below).

    ``/c/<home>/x`` -> ``C:/<home>/x``; ``/c`` and ``/c/`` -> ``C:/``, the drive
    ROOT -- never the drive-relative ``C:``, which ``ntpath`` reads as the
    current directory on that drive. The letter is upper-cased to match what
    ``os.path.expanduser`` and ``realpath`` answer with. Gated on
    ``os.name == "nt"`` like ``_is_abs_leaf``: on POSIX ``/c/...`` is an
    ordinary directory under the root and stays byte-identical.

    The helper shared by every site that compares an agent's path against a
    drive-spelled root: this module's ``_clean_path_prefixes`` (the chokepoint
    behind ``normalize_path`` / ``normalize_path_str`` / ``normalize_bash_path``
    -- protected zones on every channel and the plan gate's in-repo test; the
    secret-path check matches on the basename and never needs it),
    ``_project_root_spelling`` (the ROOT side of the same compare, when the
    variable was exported from Git Bash by hand) and ``_bash_patterns._posix``
    (the recursive-delete tier's identity, ancestor and containment rules) --
    so the spellings cannot drift apart between the guards.

    The Windows prefix spellings fold FIRST, on every host
    (``_windows_prefixes_to_drive``, DEF-935): the extended-length and device
    forms ``\\\\?\\C:\\x`` / ``\\\\.\\C:\\x``, the extended-length UNC form
    ``\\\\?\\UNC\\server\\share\\x`` and the loopback administrative shares
    ``\\\\localhost\\C$\\x`` / ``\\\\127.0.0.1\\C$\\x``, each read as the drive
    path it opens. ``ntpath.realpath`` keeps a ``\\\\?\\`` prefix its input
    carried, so without the fold the checkout compare saw ``//?/C:/...``
    against ``C:/...`` and nine of eleven such spellings of a protected file
    passed every hook on the Windows host (walk 4, 2026-09-26). Through this
    one helper the fold reaches all three sites with no edit of their own.

    Declared limits. The PowerShell write extractor shares the chokepoint, and
    by PowerShell's path grammar a rooted drive-less ``/c/x`` means ``C:\\c\\x``
    on the current drive, not ``C:\\x`` (read from the grammar; not driven on a
    host); the guard reads that token the Git Bash way. The only verdict it
    can change is a DENY of a path under a directory literally named after
    the repo's drive letter -- fail-closed, in a spelling no PowerShell user
    writes -- and a carve-out would thread the tool through the chokepoint for
    that coincidence. WSL, Cygwin and MSYS2's own Python run as ``posix``, so
    this no-ops there and root and leaf arrive in one native spelling
    (``/mnt/c/...``, ``/cygdrive/c/...``, ``/c/...``); the asymmetric
    configuration is Windows-native Python fed a POSIX-spelled path, which is
    exactly what this translates.
    """
    path = _windows_prefixes_to_drive(path)
    if os.name != "nt":
        return path
    match = _MSYS_DRIVE_RE.match(path)
    if match is None:
        return path
    return match.group(1).upper() + ":/" + path[match.end():].lstrip("/")


def _clean_path_prefixes(cleaned: str) -> str:
    """Shared pre-normalisation cleaning for normalize_path + normalize_path_str.

    Separator-canonicalise FIRST (so the env-var prefix match and downstream
    compare are separator-agnostic — closes the backslash sibling), expand
    ``~``, strip a literal ``$CLAUDE_PROJECT_DIR/`` or ``${CLAUDE_PROJECT_DIR}/``
    prefix -- or, case-insensitively, the PowerShell ``$env:CLAUDE_PROJECT_DIR/``
    / ``${env:CLAUDE_PROJECT_DIR}/`` spelling (DEF-716) -- and ``lstrip("/")``
    the residual leading slash a doubled separator leaves
    (``$CLAUDE_PROJECT_DIR//x`` → ``x``) so it stays repo-relative instead of
    reading as absolute. Extracted so both the resolve()-based normalize_path
    and the FS-free normalize_path_str share ONE cleaning chokepoint — no
    sister-site drift.

    * **NFKC fold FIRST** so a fullwidth / compatibility spelling of a separator
      or dot (U+FF0F FULLWIDTH SOLIDUS, U+FF0E FULLWIDTH FULL STOP) becomes its
      ASCII form *before* ``posixpath.normpath`` collapses ``..`` traversal.
      Folding only in ``_protected_zones._fs_equiv`` AFTER normpath would let
      ``safe／..／tools／cc／x.py`` survive normpath uncollapsed and read as
      unprotected. NFKC of an ASCII path is a no-op.
    * **Strip a leading ``file://`` scheme** so an MCP path spelled as a file://
      URI (RFC-8089 — what a filesystem MCP server resolves to the bare path)
      cannot evade the protected check by surviving normpath as a literal
      ``file:`` first component. ``file:///abs`` → ``/abs``; ``file://host/abs``
      → ``/abs`` (authority dropped, fail-closed toward the path). Other
      path-bearing URI schemes are a documented residual (FAILURE_MODES.md §6.7).
    * **Translate the drive spelling** (``_msys_drive_to_windows``: the Git
      Bash prefix ``/c/x`` → ``C:/x`` on Windows only, and on every host the
      Windows prefix spellings ``\\\\?\\C:\\x`` / ``\\\\localhost\\C$\\x`` → ``C:/x``,
      ``_windows_prefixes_to_drive``, DEF-935) before anything reads the path
      as absolute or joins it to root. After the ``file://`` strip so ``file:///c/x``
      lands in the same form; before ``~`` expansion, which never yields one.
    * **Fold separators AGAIN after ``~`` expansion.** ``ntpath.expanduser``
      splices ``USERPROFILE`` in as spelled -- ``C:\\<home>`` + ``/repo/...``
      -- so the first fold never saw those backslashes, ``_is_abs_leaf``
      (which tests ``:/``) read the result as relative, and the FS-free layer
      joined a ``~``-spelled protected path onto root and matched no zone
      while the resolve() layer, which reads both separators, denied it: the
      Layer-1/Layer-2 divergence ``_is_abs_leaf`` exists to forbid. Found by
      the DEF-731 failure-mode review two lines from that edit; a no-op on
      POSIX, where a home directory carries no backslash.
    """
    cleaned = unicodedata.normalize("NFKC", cleaned)
    cleaned = cleaned.replace("\\", "/")
    if cleaned.startswith("file://"):
        rest = cleaned[len("file://"):]
        slash = rest.find("/")
        cleaned = rest[slash:] if slash != -1 else rest
    cleaned = _msys_drive_to_windows(cleaned)
    cleaned = os.path.expanduser(cleaned) if cleaned else cleaned
    cleaned = cleaned.replace("\\", "/")   # the fold after `~`: see the docstring
    if cleaned.startswith("$CLAUDE_PROJECT_DIR/"):
        cleaned = cleaned[len("$CLAUDE_PROJECT_DIR/"):].lstrip("/")
    elif cleaned.startswith("${CLAUDE_PROJECT_DIR}/"):
        cleaned = cleaned[len("${CLAUDE_PROJECT_DIR}/"):].lstrip("/")
    else:
        # DEF-716: every PowerShell write extractor yielded the path and the
        # write still ALLOWED, because this strip knew the two bash spellings
        # of the repo root and not PowerShell's, so the candidate reached
        # `_is_protected` as a relative path beginning with a literal `$env:`
        # and matched no zone. Compared case-insensitively because that is how
        # PowerShell resolves `$Env:` / `$ENV:` (and Windows the name itself);
        # the two bash spellings above stay case-sensitive because bash is.
        # Another variable's tree (`$env:TEMP/...`) and a near-miss name
        # (`$env:CLAUDE_PROJECT_DIR_OLD/...`) fall through as literals.
        lowered = cleaned.lower()
        for prefix in _PS_ENV_PROJECT_DIR_PREFIXES:
            if lowered.startswith(prefix):
                cleaned = cleaned[len(prefix):].lstrip("/")
                break
    return cleaned


def _rel_under_root(abs_posix: str, root_posix: str) -> str | None:
    """Repo-relative remainder of an absolute POSIX path under ``root_posix``,
    or ``None`` if it is not under root.

    The compare is CASE-INSENSITIVE: macOS APFS / Windows NTFS are
    case-insensitive, so the lower-case and capitalised spellings of the macOS
    home prefix name the SAME
    file -- a case-sensitive prefix compare misses a case-variant absolute path
    under root and lets it escape the protected check. This mirrors the
    unconditional case-fold the protected-zone compare (``_fs_equiv``) already
    uses; on a case-SENSITIVE filesystem it over-protects a genuinely-different-
    case path, which is the safe fail-closed direction.

    The returned remainder preserves the input's original case; the downstream
    ``_fs_equiv`` fold casefolds it for the actual prefix/exact-match compare.
    """
    a = abs_posix.casefold()
    r = root_posix.casefold()
    if a == r:
        return ""
    if a.startswith(r + "/"):
        return abs_posix[len(root_posix) + 1:]
    return None


def _is_abs_leaf(cleaned: str) -> bool:
    """True if a forward-slash-normalised leaf names an ABSOLUTE path.

    A leading ``/`` is absolute on every platform. A ``<drive>:/`` prefix is
    absolute on WINDOWS only. Layer 1 (``normalize_path``) gets this for free
    from ``Path.is_absolute()`` (True for ``C:/x`` on Windows, False on POSIX);
    the FS-free Layer 2 (``normalize_path_str``) does its own string test and
    must MATCH it, or a Windows absolute path under root
    (``C:/repo/tools/cc/hooks/x``) is read as relative, joined to root a SECOND
    time, and escapes the protected-prefix compare -- a bypass (the residual
    the case-variant-absolute adversarial pass would surface on a Windows host).
    Gated on ``os.name == "nt"`` so the two layers stay in lockstep and POSIX
    is byte-identical: there ``C:/x`` is a relative file in a ``C:`` subdir, not
    an absolute path.
    """
    if cleaned.startswith("/"):
        return True
    return (
        os.name == "nt"
        and len(cleaned) >= 3
        and cleaned[0].isalpha()
        and cleaned[1:3] == ":/"
    )


# ── Sibling checkouts: a worktree of the repository is governed like the root ─
#
# A Claude Code session that enters a git worktree keeps ``CLAUDE_PROJECT_DIR``
# at the project root while every path it edits sits under the worktree (the
# ``cc-worktrees`` external pin), so a target relativised against the root alone
# read ``.claude/worktrees/<name>/tools/cc/x.py`` -- no protected prefix, and
# plan-exempt under ``.claude/`` -- and both blocking guards covered nothing
# there (DEF-743, driven 2026-09-09). Every normaliser in this section therefore
# relativises against the checkout that CONTAINS the target: the root, or a
# registered worktree of the same repository, nested under the root or beside
# it. The worktree list is git's own registry read straight off the disk
# (``<common>/worktrees/<id>/gitdir``, git-worktree(1)), never a subprocess.

#: Per-process memos for `sibling_checkouts` / `_checkout_bases`, keyed on the
#: root's spelling. The MCP leaf-walk may relativise thousands of leaves in one
#: hook run and must stay free of per-leaf syscalls (`normalize_path_str`'s
#: contract); the checkout list is a handful of small reads that cannot change
#: inside one tool call. Hook processes are short-lived, so process scope is
#: the right scope. A test process is not: every hook copy binds this one
#: module object, so `tests/conftest.py::_isolate_interpreter_identity_memo`
#: clears both memos around every test (a worktree registered after a first
#: read would otherwise stay invisible to the rest of the worker).
_SIBLING_CHECKOUTS_MEMO: dict[str, tuple[Path, ...]] = {}
_CHECKOUT_BASES_MEMO: dict[str, tuple[str, ...]] = {}
#: The registry walk is linear in the number of entries and runs once per hook
#: process, on every tool call: 300 entries measured about 14 ms on a local
#: disk (the failure-mode review), and a network filesystem multiplies that.
#: Entries past the cap are not checkouts to this process (toward the
#: pre-DEF-743 behaviour, never a wall); a registry that large is a
#: `git worktree prune` away.
_REGISTRY_ENTRY_CAP = 256


def _git_dir_of(checkout: Path) -> Path | None:
    """The git directory a checkout's ``.git`` entry names, resolved: the
    ``.git`` directory itself, or the target of a ``gitdir: <path>`` gitlink
    file (a worktree, a submodule, a ``--separate-git-dir`` clone), read
    relative to the checkout when spelled so. ``None`` without a usable entry.
    """
    marker = checkout / ".git"
    try:
        if marker.is_dir():
            return marker.resolve()
        if not marker.is_file():
            return None
        lines = marker.read_text(encoding="utf-8", errors="replace").splitlines()
    except (OSError, ValueError):  # fail-open: ok deliberate -- an unreadable .git marker is not a checkout of this repository; the root stays governed
        return None
    line = lines[0].strip() if lines else ""
    if not line.startswith("gitdir:"):
        return None
    target = line[len("gitdir:"):].strip()
    if not target:
        return None
    try:
        return (checkout / target).resolve()
    except (OSError, ValueError):  # fail-open: ok deliberate -- an unresolvable gitdir target is not a checkout; the root stays governed
        return None


def _same_dir(a: Path, b: Path) -> bool:
    """Identity by inode when the filesystem answers (a case-variant spelling
    on APFS / NTFS names the same directory), by spelling otherwise."""
    try:
        return a.samefile(b)
    except (OSError, ValueError):
        return a == b


def _sibling_checkouts_uncached(root: Path) -> tuple[Path, ...]:
    if not isinstance(root, Path):
        return ()  # a pure path has no filesystem behind it (the FS-free tests' roots)
    try:
        here = root.resolve()
        git_dir = _git_dir_of(here)
        if git_dir is None:
            return ()
        common = git_dir
        found: list[Path] = []
        commondir = git_dir / "commondir"
        if commondir.is_file():
            # ``root`` is itself a worktree: its git dir is ``<common>/worktrees/<id>``
            # and ``commondir`` names the shared one (``../..``); the main checkout
            # is the shared dir's parent (a bare repository has no checkout there).
            shared = commondir.read_text(encoding="utf-8", errors="replace").strip()
            common = (git_dir / shared).resolve()
            if common.name == ".git" and common.parent.is_dir():
                found.append(common.parent)
        registry = common / "worktrees"
        if registry.is_dir():
            for entry in sorted(registry.iterdir())[:_REGISTRY_ENTRY_CAP]:
                try:
                    line = (entry / "gitdir").read_text(encoding="utf-8", errors="replace").strip()
                except (OSError, ValueError):
                    continue
                if not line:
                    continue
                # Absolute in every git before ``--relative-paths`` (2.48), relative
                # to ``<entry>`` after; names the worktree's ``.git`` FILE, whose
                # parent is the checkout.
                checkout = (entry / line).resolve().parent
                if checkout.is_dir() and not _same_dir(checkout, here):
                    found.append(checkout)
        return tuple(found)
    except (OSError, ValueError, NotImplementedError):  # fail-open: ok deliberate -- an unreadable worktree registry lists no siblings; the root checkout stays governed
        # NotImplementedError: a Path flavour this host cannot operate (the
        # emulated-Windows tests read ``os.name`` as ``nt`` on a POSIX host).
        return ()


def sibling_checkouts(root: Path) -> tuple[Path, ...]:
    """Every OTHER checkout of the repository ``root`` belongs to, resolved:
    its registered worktrees (nested under it or beside it), and the main
    checkout when ``root`` is itself a worktree.

    Read from git's own registry on disk -- ``<common>/worktrees/<id>/gitdir``
    names each worktree's ``.git`` file (git-worktree(1)) -- so it needs no
    subprocess and costs a handful of small reads, memoised per process. A
    worktree whose directory is gone (prunable, not yet pruned) is skipped. A
    nested clone or a submodule is not a checkout of this repository and is
    never listed: their ``.git`` points elsewhere and the registry does not
    know them. Never raises; a repository it cannot read has no siblings.

    Declared limits, each toward the pre-DEF-743 behaviour (that checkout is
    simply not governed), never toward a wall: a registry entry whose
    ``gitdir`` file is missing or unreadable is skipped; from inside a worktree
    of a ``--separate-git-dir`` clone the main checkout is not found (its
    common dir is not named ``.git``, and nothing in it points back at the
    checkout); entries past ``_REGISTRY_ENTRY_CAP`` are not read; and a bare
    common dir has no main checkout at all.
    """
    key = str(root)
    if key not in _SIBLING_CHECKOUTS_MEMO:
        _SIBLING_CHECKOUTS_MEMO[key] = _sibling_checkouts_uncached(root)
    return _SIBLING_CHECKOUTS_MEMO[key]


def sibling_checkout_containing(root: Path, path: Path) -> Path | None:
    """The sibling checkout of ``root`` (see ``sibling_checkouts``) that
    contains ``path`` -- a worktree beside or under the root -- or ``None``.
    Compares resolved spellings case-insensitively; never raises."""
    try:
        here = str(path.resolve()).replace("\\", "/")
    except (OSError, ValueError, NotImplementedError):  # fail-open: ok deliberate -- a path that cannot be resolved sits in no sibling checkout; the root's rules apply
        return None
    for checkout in sibling_checkouts(root):
        if _rel_under_root(here, str(checkout).replace("\\", "/").rstrip("/")) is not None:
            return checkout
    return None


def is_sibling_checkout(root: Path, path: Path) -> bool:
    """Is ``path`` itself one of ``root``'s sibling checkouts -- a registered
    worktree of the repository, rather than a foreign clone dropped into the
    tree? Identity by inode where the filesystem answers; never raises."""
    try:
        candidate = path.resolve()
    except (OSError, ValueError, NotImplementedError):  # fail-open: ok deliberate -- a path that cannot be resolved is not a sibling checkout
        return False
    return any(_same_dir(candidate, checkout) for checkout in sibling_checkouts(root))


def _checkout_bases(root: Path) -> tuple[str, ...]:
    """The forward-slash spellings a target may be relativised against, LONGEST
    first so the deepest containing checkout wins: ``root`` as given, its
    resolved spelling when that differs, and every sibling checkout."""
    key = str(root)
    if key in _CHECKOUT_BASES_MEMO:
        return _CHECKOUT_BASES_MEMO[key]
    spellings = [key.replace("\\", "/").rstrip("/")]
    if isinstance(root, Path):
        try:
            spellings.append(str(root.resolve()).replace("\\", "/").rstrip("/"))
        except (OSError, ValueError, NotImplementedError):
            pass
    spellings.extend(str(c).replace("\\", "/").rstrip("/") for c in sibling_checkouts(root))
    ordered = tuple(sorted(dict.fromkeys(spellings), key=len, reverse=True))
    _CHECKOUT_BASES_MEMO[key] = ordered
    return ordered


def containing_checkout(abs_posix: str, root: Path) -> tuple[str, str] | None:
    """``(base, rel)`` for an absolute, forward-slash-spelled path: the deepest
    checkout containing it (``root`` or a sibling, per ``_checkout_bases``) and
    the remainder under it, compared case-insensitively (``_rel_under_root``).
    ``None`` when no checkout contains the path. Pure string work after the
    memoised base list, so the FS-free leaf-walk may call it per leaf."""
    for base in _checkout_bases(root):
        rel = _rel_under_root(abs_posix, base)
        if rel is not None:
            return base, rel
    return None


def _base_path(base: str, root: Path) -> Path:
    """The checkout ``containing_checkout`` named, as a path: ``root`` itself
    for the root's own spelling, else the sibling's."""
    return root if base == str(root).replace("\\", "/").rstrip("/") else Path(base)


def resolve_in_checkout(
    file_path: object, root: Path, *, base: Path | None = None,
) -> tuple[Path, str]:
    """``(base, rel)`` for a tool path: the checkout containing it (``root`` or
    a sibling worktree, see ``sibling_checkouts``) and its path relative to
    that checkout -- the string ``normalize_path`` returns. The base is for the
    sites that rejoin the relative path to a directory afterwards (the hardlink
    backstop's stat, post_write_check's read and prune); the compare key
    everywhere is the relative path.

    ``base`` (DEF-509) is the directory a RELATIVE spelling resolves against:
    the working directory the command runs in, when the caller knows it (the
    hook payload's ``cwd``, a leading ``cd`` in a Bash command). The default
    is the checkout root, which every caller assumed until 2026-09-13 -- and
    which is wrong as soon as Claude has changed directory, because the Bash
    tool's directory persists across calls and the payload's ``cwd`` follows
    it.

    Falls back to ``(root, <cleaned spelling>)`` when nothing contains the path
    or it cannot be resolved -- the raw-string fallback ``normalize_path``
    documents -- and to ``(root, "<invalid>")`` for a non-str payload.
    """
    if not isinstance(file_path, str):
        return root, "<invalid>"
    cleaned = _clean_path_prefixes(file_path)
    p = Path(cleaned)
    try:
        resolved = (p if p.is_absolute() else ((base or root) / p)).resolve()
        hit = containing_checkout(str(resolved).replace("\\", "/"), root)
    except (ValueError, OSError):
        return root, cleaned.replace("\\", "/")
    if hit is None:
        # Outside every checkout. A relative spelling read against a caller's
        # base answers with where it LANDS, not with the spelling: otherwise
        # `cd /tmp && echo x > tools/cc/hooks/f.py` hands back the protected-
        # looking relative string and is denied for a write that never touches
        # the tree (DEF-509). Without a base the spelling stands, as before.
        if base is not None and not p.is_absolute():
            return root, str(resolved).replace("\\", "/")
        return root, cleaned.replace("\\", "/")
    # The checkout itself answers "." (what `relative_to` said before the
    # checkout-aware compare), pinned by the reflect_trigger normalisation suite.
    return _base_path(hit[0], root), hit[1] or "."


def normalize_path_str(value: object, root: Path) -> str:
    """FS-free path normaliser for the MCP leaf-walk.

    Same prefix/separator/expanduser cleaning as ``normalize_path`` (via the
    shared ``_clean_path_prefixes``), but collapses ``..`` with
    ``posixpath.normpath`` (pure string) instead of ``Path.resolve()``. The
    leaf-walk may visit many / long string leaves; resolve()'s per-component
    ``lstat`` would make a large payload a slow-hook fail-open (cf. the
    _PERL_OPEN_RE ReDoS critical). normpath is O(n) with zero syscalls.

    Symlink-following is deliberately NOT performed here (that is
    read_text_nofollow's job). The result is fed to ``_protected_zones._is_protected`` /
    ``_is_allowed``, which apply the ``_fs_equiv`` (ADS / trailing-dot / NFKC /
    casefold) fold on top, so this only has to produce a faithful repo-relative
    string for the prefix / exact-match compare.

    An absolute path that lies under ``root`` -- or under a sibling checkout
    of the repository, a registered worktree (DEF-743) -- is relativised by
    string prefix; a bare leading-slash or out-of-repo absolute path is left
    as-is (it names a DIFFERENT file and correctly does not match a
    repo-relative protected prefix — consistent with the documented
    bare-leading-slash known-limit). The prefix compare is lexical, so a
    checkout named through a symlink (a ``/tmp`` spelling of a ``/private/tmp``
    worktree, a link beside a registered path) is matched only by the spelling
    git registered; that is the same residual the root has always had on this
    layer, and Layer 1 (``normalize_path``, which resolves) closes it.
    """
    if not isinstance(value, str):
        return "<invalid>"
    cleaned = _clean_path_prefixes(value)
    if not cleaned:
        return cleaned
    root_posix = str(root).replace("\\", "/").rstrip("/")
    if _is_abs_leaf(cleaned):
        # Absolute leaf (leading ``/`` anywhere, or a ``C:/`` drive on Windows):
        # collapse lexically, then relativise (case-insensitive). Detecting the
        # Windows drive-letter form here is what keeps Layer 2 in lockstep with
        # Layer 1's ``Path.is_absolute()`` -- without it a ``C:/repo/...`` leaf
        # is misread as relative and rejoined to root, escaping the compare.
        collapsed = posixpath.normpath(cleaned)
    else:
        # Relative leaf: JOIN to root BEFORE normpath so a leading ``..`` that
        # re-enters the repo (``../<reponame>/tools/...``) collapses against
        # root the way resolve() would -- lexically, FS-free. posixpath.normpath
        # ALONE cannot drop a LEADING ``..``, so the parent-escape-and-reenter
        # bypass would leave the leaf resolving to the protected file but staying
        # out-of-prefix as a bare ``../<repo>/...`` string.
        collapsed = posixpath.normpath(posixpath.join(root_posix, cleaned))
    hit = containing_checkout(collapsed, root)
    # Under a checkout (root or a sibling worktree) -> the remainder relative to
    # it; otherwise the collapsed absolute (out-of-repo, correctly will NOT match
    # a repo-relative protected prefix). The checkout list is memoised per
    # process, so this stays syscall-free per leaf.
    return hit[1] if hit is not None else collapsed


def iter_mcp_path_leaves(tool_input: object) -> Iterator[tuple[str, str, str]]:
    """Yield ``(key, location, value)`` for every non-empty STRING leaf of an
    MCP ``tool_input``, recursing dicts (values) and lists/tuples.

    * ``key`` — the nearest enclosing DICT key governing this leaf (a list
      inherits its parent key), e.g. ``"path"`` for ``{files:[{path:…}]}`` and
      ``"files"`` for ``{files:["a.py"]}``. Consumers use it to apply a policy
      filter (write_guard skips ``MCP_CONTENT_KEYS``; plan_guard acts only on
      ``MCP_PATH_FIELDS``) — the iterator itself is policy-neutral.
    * ``location`` — a human-readable path for the deny reason
      (``"batch.files[0].path"``).

    Key-agnostic + depth/node-bounded; raises ``MCPPayloadUnverifiable`` past
    ``MCP_LEAFWALK_MAX_DEPTH`` / ``MCP_LEAFWALK_MAX_NODES`` so the caller fails
    CLOSED. Non-string scalars (int/float/bool/None) are not path-shaped and
    are ignored.
    """
    counter = [0]

    def _walk(obj: object, key: str, location: str, depth: int) -> Iterator[tuple[str, str, str]]:
        if depth > MCP_LEAFWALK_MAX_DEPTH:
            raise MCPPayloadUnverifiable(f"nesting deeper than {MCP_LEAFWALK_MAX_DEPTH}")
        counter[0] += 1
        if counter[0] > MCP_LEAFWALK_MAX_NODES:
            raise MCPPayloadUnverifiable(f"more than {MCP_LEAFWALK_MAX_NODES} nodes")
        if isinstance(obj, str):
            if obj:
                yield (key, location or "<root>", obj)
        elif isinstance(obj, dict):
            for k, v in obj.items():
                k_str = str(k)
                child_loc = f"{location}.{k_str}" if location else k_str
                yield from _walk(v, k_str, child_loc, depth + 1)
        elif isinstance(obj, (list, tuple)):
            for i, v in enumerate(obj):
                # List items inherit the governing key of the enclosing dict.
                yield from _walk(v, key, f"{location}[{i}]", depth + 1)

    yield from _walk(tool_input, "", "", 0)


def normalize_bash_path(raw: str, root: Path, *, base: Path | None = None) -> str:
    """Normalize a path captured from a Bash command.

    Same separator-canonicalise-then-lstrip discipline as `normalize_path`. The
    Bash channel adds a leading-``./`` strip that, on a ``.//`` (double-slash)
    prefix, would leave a leading slash after the 2-char slice and read as
    absolute. The ``lstrip("/")`` after both the ``./`` strip and each env-var
    strip collapses that residual slash to a repo-relative path. ``replace("\\","/")``
    at the top makes the strips separator-agnostic. The fallback still delegates
    to `normalize_path` with the quote-stripped, canonicalised ``cleaned``.
    Relative to the checkout containing the path, like ``normalize_path``;
    ``resolve_bash_in_checkout`` is the owner and also returns that checkout.
    ``base`` is the directory a relative spelling resolves against (DEF-509;
    see ``resolve_in_checkout``).
    """
    return resolve_bash_in_checkout(raw, root, base=base)[1]


def resolve_bash_in_checkout(
    raw: str, root: Path, *, base: Path | None = None,
) -> tuple[Path, str]:
    """``(base, rel)`` for a path captured from a Bash command: the
    ``normalize_bash_path`` cleaning, then the checkout containing the result
    and the path relative to it (``resolve_in_checkout``'s contract; the base
    is for the hardlink backstop's stat). ``base`` is the directory a relative
    spelling resolves against (DEF-509; see ``resolve_in_checkout``)."""
    cleaned = raw.strip().strip('"').strip("'")
    # ONE cleaning chokepoint, shared with normalize_path / normalize_path_str:
    # NFKC fold, separator canonicalise, ~ expansion, `$CLAUDE_PROJECT_DIR/`
    # (the bash and the PowerShell `$env:` spellings) and `file://` stripping,
    # residual-slash collapse.
    #
    # This channel previously hand-maintained a SECOND copy of that chain that
    # omitted the NFKC fold, so the Write channel denied a fullwidth-solidus
    # traversal the Bash channel allowed. That asymmetry is the defect -- not the
    # traversal: the no-traversal fullwidth spelling was already denied on Bash
    # via `_protected_zones._fs_equiv`'s per-component fold, and only the
    # traversal spelling (which needs the fold BEFORE normpath) escaped. The
    # value here is the ~3-line dedup at least as much as the class it closes.
    cleaned = _clean_path_prefixes(cleaned)
    if cleaned.startswith("./"):
        # Bash-only: `.//x` would leave a leading slash after the 2-char slice
        # and read as absolute; lstrip collapses it to repo-relative.
        cleaned = cleaned[2:].lstrip("/")
    # Resolve traversal sequences (e.g. tools/cc/../../.claude/settings.json)
    try:
        resolved = ((base or root) / cleaned).resolve()
        hit = containing_checkout(str(resolved).replace("\\", "/"), root)
        if hit is not None:
            return _base_path(hit[0], root), hit[1] or "."
    except (ValueError, OSError):
        pass
    return resolve_in_checkout(cleaned, root, base=base)


def payload_cwd(data: object, root: Path) -> Path | None:
    """The hook payload's ``cwd`` as a directory (DEF-509): the directory
    Claude is in, which Claude Code moves when an earlier call ran `cd`, so a
    relative spelling in THIS call resolves against it. ``None`` when the
    payload carries none (an older client, a test that omits it) or an
    unusable one; a relative spelling is read against the root. Shared by
    write_guard (the verdict) and post_write_check (the registry payloads),
    so the two hooks read one directory."""
    raw = data.get("cwd") if isinstance(data, dict) else None
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        p = Path(raw.strip())
        return p if p.is_absolute() else (root / p)
    except (ValueError, OSError):  # fail-open: ok deliberate -- an unusable payload cwd falls back to the checkout root (DEF-509)
        return None


def hook_cwd(payload: object) -> Path | None:
    """The directory Claude is working in, from the hook input's ``cwd``,
    RESOLVED. Every hook input carries ``cwd`` ("Current working directory when
    the hook is invoked"), and after Claude enters a worktree it is the worktree
    root while ``CLAUDE_PROJECT_DIR`` stays at the project root (the Claude Code
    worktrees page; espalier pins the sentences as its ``cc-worktrees`` external
    pin). ``None`` when the payload has no usable ``cwd`` -- absent, empty, not
    a string, not absolute (upstream documents it absolute; a relative spelling
    would resolve against the hook's own cwd and name the wrong tree), or
    unresolvable. ONE home for the two writers of the session marker's ``cwd``
    (session_start's marker job and task_router's heartbeat) and session_start's
    litter finder, so the value the banner compares with the resolved root is
    produced one way; ``payload_cwd`` above is the guards' reading (DEF-509: a
    relative spelling against the root, unresolved), a different question.
    Never raises."""
    raw = payload.get("cwd") if isinstance(payload, dict) else None
    if not isinstance(raw, str) or not raw:
        return None
    try:
        candidate = Path(raw)
        if not candidate.is_absolute():
            return None
        return candidate.resolve()
    # fail-open: ok deliberate -- an unusable payload cwd falls back to the root
    except (OSError, ValueError):  # ValueError: an embedded NUL, a malformed Windows spelling
        return None


def directory_exists(start: Path) -> "Callable[[str], bool]":
    """The directory chain's oracle (`_bash_patterns.bash_directory_chain`):
    is the directory it spelled there, joined to the start? A `cd` to one
    that is not leaves the shell where it was. ONE home for write_guard and
    post_write_check, so a rule about what counts as "there" (a directory the
    same command makes is credited by the walk itself) reaches both."""
    def exists(spelled: str) -> bool:
        try:
            return join_directory(start, spelled).is_dir()
        except (OSError, ValueError):  # fail-open: ok deliberate -- a directory the cd-walk cannot read is not entered; the command is judged where it stands
            return False
    return exists


def join_directory(start: Path, spelled: str | None) -> Path:
    """A directory the command's chain spelled (`_bash_patterns.
    bash_directory_chain`), joined to the start it is relative to; an
    unreadable one (``None``) is the start itself -- the indirection class
    resolves as the root always did."""
    if spelled is None or spelled == ".":
        return start
    if spelled.startswith("~"):
        return Path(spelled).expanduser()
    # A Git Bash drive spelling (`/c/<home>/x`) is absolute on the host that
    # produces it, and `Path` on Windows anchors it onto the current drive as
    # `C:\\c\\<home>\\x` -- a directory that is not there -- so the walk read
    # every `cd "/c/..."` as a failed cd, left the shell at the root, and a
    # write under the checkout after one was waved through (six quoted-target
    # rows on windows-latest, 2026-09-24). The tool-path normaliser already
    # translates this form (`_clean_path_prefixes`); the chain's one home does
    # too. `_msys_drive_to_windows` is a no-op off Windows.
    p = Path(_msys_drive_to_windows(spelled))
    return p if p.is_absolute() else (start / p)


# ── Host orientation (shared by subagent_start + _reinject) ──────────────────
# The host+interpreter resolution line. Extracted here so the SubagentStart cold-
# orientation (subagent_start._orientation_line) and the SessionStart parent-
# orientation (_reinject._render_orientation) resolve it ONE way, not two.
# Mode flags (MAINTENANCE / STOP_GATE) are intentionally NOT here — each caller
# formats those differently (subagent_start emits them unconditionally; _reinject
# emits them conditionally), so this returns only the always-present host facts.
#: Per-process memo for `interpreter_is_python3`. PATH does not change inside a
#: hook process, and both consumers probe overlapping names -- session_start walks
#: every wired interpreter while host_orientation_line probes two -- so without
#: this a single SessionStart would spawn the same subprocess repeatedly on the
#: start path. Hook processes are short-lived, so process scope is the right scope.
_INTERPRETER_IDENTITY_MEMO: dict = {}


def interpreter_is_python3(name_or_path: str) -> bool:
    """Does ``name_or_path`` actually ANSWER as a Python 3 interpreter?

    ``shutil.which(name) is not None`` answers "does something answer to this
    name", which is a different question. A Microsoft Store App Execution Alias,
    a stale Python-2 symlink and an unset pyenv shim all satisfy the first and
    fail this one. On such a host the hook still spawns, exits outside the
    ``{0, 2}`` range the protocol treats as a decision, and a non-decision is
    NON-BLOCKING -- so every blocking guard fails OPEN while `init` reports
    success.

    Duplicated from `espalier.doctor._interpreter_is_python3` because
    `tools/cc/` may not import espalier. The two are parity-pinned by
    `tests/test_hooks.py`, following this repo's `decode_bom` three-copy
    precedent: duplicated identity logic here gets a parity test rather than a
    note asking a future reader to remember.

    A launcher spelling (``py -3``) is probed as the launcher with its flag.
    """
    if not name_or_path:
        return False
    if name_or_path in _INTERPRETER_IDENTITY_MEMO:
        return _INTERPRETER_IDENTITY_MEMO[name_or_path]
    import shutil
    import subprocess
    head, *flags = interpreter_argv(name_or_path)
    resolved = shutil.which(head) or (
        head if Path(head).is_file() else None
    )
    verdict = False
    if resolved:
        # See the engine-side twin: never spawn a probe for the interpreter
        # already running this code. Removes the spawn AND the false alarm on a
        # host where spawning is blocked.
        try:
            if not flags and os.path.samefile(resolved, sys.executable):
                _INTERPRETER_IDENTITY_MEMO[name_or_path] = True
                return True
        except OSError:
            pass
        try:
            result = subprocess.run(  # spawn: ok the interpreter probe resolves its own token through shutil.which above; a probe that cannot run is a False verdict the banner names
                [resolved, *flags, "--version"], capture_output=True, text=True,
                encoding="utf-8", timeout=2,
            )
            # Through the ONE banner rule (`is_python3_banner`), not
            # `startswith("Python 3.")`: the floor parser searches anywhere in
            # the output, and a banner with a line before it made identity and
            # the floor disagree about one interpreter (DEF-727 review).
            verdict = is_python3_banner((result.stdout or result.stderr).strip())
        # fail-open: ok deliberate -- an interpreter that cannot answer is not python3, and the banner's unresolved-interpreter warning names it
        except (subprocess.SubprocessError, OSError, ValueError):  # strict decode: a structured answer (DEF-821)
            verdict = False
    _INTERPRETER_IDENTITY_MEMO[name_or_path] = verdict
    return verdict


#: The minimum Python this package declares in ``pyproject.toml``
#: (``requires-python = ">=3.10"``). Byte-parity twin of
#: ``espalier._python_floor.MIN_PYTHON`` -- duplicated because ``tools/cc/`` may
#: not import espalier, and NOT derivable at runtime: these hooks run inside an
#: ADOPTER's tree, where the only ``pyproject.toml`` is the adopter's own and
#: says nothing about espalier's floor. Pinned by
#: ``tests/test_python_floor.py::TestTwoCopyParity``.
MIN_PYTHON: tuple = (3, 10)

#: Same shape as the engine-side ``_VERSION_RE``. Tolerates a missing patch level
#: (``Python 3.10``) and a pre-release suffix (``Python 3.14.0rc1``).
_PY_VERSION_RE = re.compile(r"Python\s+(\d+)\.(\d+)")


def parse_python_version(version_output: str) -> tuple[int, int] | None:
    """``(major, minor)`` from ``python --version`` output, or None.

    Parity twin of ``espalier._python_floor.parse_python_version``. None means
    "not a version banner" -- empty output, a shell error, or a resolving
    non-interpreter -- and every caller reads None as "does not clear the
    floor", never as "assume it is fine".
    """
    if not version_output:
        return None
    match = _PY_VERSION_RE.search(version_output)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def meets_python_floor(version_output: str) -> bool:
    """True when ``version_output`` reports at least :data:`MIN_PYTHON`.

    Parity twin of ``espalier._python_floor.meets_python_floor``. ``Python
    3.9.6`` is False -- the case the identity probe above deliberately accepts,
    because 3.9 IS a Python 3 and saying otherwise would put a false host fact
    in the orientation line. Identity and capability are separate questions;
    this is the capability one.
    """
    parsed = parse_python_version(version_output)
    return parsed is not None and parsed >= MIN_PYTHON


def is_python3_banner(version_output: str) -> bool:
    """A Python 3 version banner -- identity, read off the MAJOR.

    Parity twin of ``espalier._python_floor.is_python3_banner`` (pinned by
    ``tests/test_python_floor.py::TestTwoCopyParity``): the one rule
    :func:`interpreter_is_python3` reads its ``--version`` output through, so
    identity and the floor cannot disagree about a banner. ``Python 4.0`` is
    not a Python 3; the floor decides what to do with it.
    """
    parsed = parse_python_version(version_output)
    return parsed is not None and parsed[0] == 3


def floor_text() -> str:
    """``"3.10"`` -- parity twin of ``espalier._python_floor.floor_text``.

    One renderer per tree, so an operator-facing message can never quote a
    floor the code does not enforce.
    """
    return ".".join(str(part) for part in MIN_PYTHON)


#: One Windows Python Launcher version flag (``-3``, ``-3.11``, ``-3.11-64``),
#: consumed by the launcher before the interpreter starts. Twin of
#: ``espalier._python_floor.LAUNCHER_VERSION_FLAG`` across the no-import
#: boundary, pinned equal by ``tests/test_python_floor.py::TestTwoCopyParity``.
LAUNCHER_VERSION_FLAG = re.compile(r"-3(\.\d+)?(-(32|64|arm64))?")


def is_python_launcher(token: str) -> bool:
    """True if ``token`` is the Windows Python Launcher, ``py`` or ``py.exe``,
    optionally a full path. Twin of ``espalier._python_floor.is_python_launcher``."""
    base = token.replace("\\", "/").rsplit("/", 1)[-1]
    base = base.lower()
    if base.endswith(".exe"):
        base = base[: -len(".exe")]
    return base == "py"


#: The Windows launcher spelling: what ``init`` wires on a host where only the
#: launcher runs, and what the orientation line names there. Twin of
#: ``espalier.cli.LAUNCHER_CANDIDATE``, pinned equal by
#: ``tests/test_python_floor.py::TestTwoCopyParity``.
LAUNCHER_SPELLING = "py -3"


def interpreter_argv(spelling: str) -> list[str]:
    """``"py -3"`` -> ``["py", "-3"]``; every other spelling stays one word.
    Twin of ``espalier._python_floor.interpreter_argv``: only the launcher
    followed by exactly one version flag is split, so a spaced path is safe."""
    # Split at the LAST space, so a launcher path that itself holds a space
    # (`C:/Program Files/.../py.exe -3`) still splits into its two words.
    head, _, flag = spelling.strip().rpartition(" ")
    head = head.rstrip()
    if head and is_python_launcher(head) and LAUNCHER_VERSION_FLAG.fullmatch(flag):
        return [head, flag]
    return [spelling]


def launcher_spelling(interp: str, rest: list) -> str:
    """``interp``, or ``interp <flag>`` when ``interp`` is the launcher and
    ``rest`` (the words after it, or an exec-form entry's ``args``) opens with
    its version flag: the spelling a floor probe must ask, because a bare
    ``py`` asks the launcher's default interpreter, not the one ``-3`` runs.
    Twin of the engine's ``espalier.cli._launcher_spelling_of``."""
    if (is_python_launcher(interp) and rest and isinstance(rest[0], str)
            and LAUNCHER_VERSION_FLAG.fullmatch(rest[0])):
        return f"{interp} {rest[0]}"
    return interp


def interpreter_meets_floor(name_or_path: str) -> bool:
    """Does ``name_or_path`` answer as a Python that clears :data:`MIN_PYTHON`?

    The capability sibling of :func:`interpreter_is_python3`. Use this wherever
    a DECISION is made -- warn about a wired interpreter, refuse to wire one --
    and the identity probe only where a host FACT is being reported.

    A stock ``/usr/bin/python3`` on macOS is 3.9.6: identity True, floor False.
    That gap is the entire defect this pair was split to express (``DEF-636``);
    before the floor existed there was only the identity question, and it was
    answering the capability one by accident.

    A launcher spelling (``py -3``) is probed as the launcher with its flag.

    ⚠ The BANNER only: unlike the engine's ``_python_floor.interpreter_meets_floor``,
    this runs no start-up probe (``DEF-915``), because ``--version`` is answered
    before an interpreter initialises and a spawn here is paid on every
    SessionStart. So it may WARN, never decide to WIRE: an interpreter that
    prints a 3.10+ banner and cannot start passes it. Wiring is the engine's.
    """
    if not name_or_path:
        return False
    key = ("floor", name_or_path)
    if key in _INTERPRETER_IDENTITY_MEMO:
        return _INTERPRETER_IDENTITY_MEMO[key]
    import shutil
    import subprocess
    head, *flags = interpreter_argv(name_or_path)
    resolved = shutil.which(head) or (
        head if Path(head).is_file() else None
    )
    verdict = False
    if resolved:
        # No `samefile(sys.executable)` short-circuit here, unlike the identity
        # probe. That shortcut is safe for "is this a Python 3" because the
        # process running this code demonstrably is one -- but it CANNOT answer
        # the floor question: a hook spawned by a 3.9 interpreter would
        # short-circuit to True and bless exactly the host this check exists to
        # catch. The version has to be read.
        try:
            result = subprocess.run(  # spawn: ok the floor probe resolves its own token through shutil.which above; a probe that cannot run is a False verdict the banner names
                [resolved, *flags, "--version"], capture_output=True, text=True,
                encoding="utf-8", timeout=2,
            )
            verdict = meets_python_floor((result.stdout or result.stderr).strip())
        # fail-open: ok deliberate -- an interpreter that cannot answer is below the floor, and the banner's warning names it
        except (subprocess.SubprocessError, OSError, ValueError):  # strict decode: a structured answer (DEF-821)
            verdict = False
    _INTERPRETER_IDENTITY_MEMO[key] = verdict
    return verdict


def python_command_hint() -> str:
    """The interpreter name to SPELL in a message telling the operator to run
    something -- resolved on this host, never assumed.

    ``DEF-383a``: hook messages hard-coded ``python``, which does not exist on a
    stock macOS (only ``python3``), so the harness's own remediation was
    unrunnable on the modal Mac -- observed live when the decision-shape
    advisory told this session to run ``python tools/cc/...``. The mirror-image
    fix, sweeping to ``python3``, is equally wrong: many Windows installs ship
    only ``python``, which is why
    ``tests/test_portability_contract.py::test_no_bare_interpreter_token``
    BANS the versioned spelling in operator text. Neither literal is portable,
    so neither belongs in a message. Interpolate this instead.

    Falls back to ``sys.executable`` -- an absolute path, always correct and
    paste-able -- rather than guessing a bare name that may not resolve. Verbose
    beats wrong in a remediation the operator is about to run.

    ⚠ Returns "" when NOTHING on this host clears the floor, and callers MUST
    check. The first version fell back to ``sys.executable`` unchecked, which
    on the very host DEF-636 names -- stock macOS, ``/usr/bin/python3`` 3.9.6 --
    handed the operator ``/usr/bin/python3 tools/cc/cognitive_blueprint.py``,
    a guaranteed SyntaxError (that file is 3.10+ ``match``). A remediation that
    cannot run is DEF-383a one layer down, inside the helper written to end it.
    Printing no command beats printing a broken one.
    """
    # The launcher last: on a host where only `py -3` runs (a python.org
    # install that left PATH alone, the two names Store aliases), it is the
    # spelling the orientation line names, and the absolute path below would
    # be a second, longer answer to the same question.
    for candidate in ("python3", "python", LAUNCHER_SPELLING):
        if interpreter_meets_floor(candidate):
            return candidate
    if sys.executable and interpreter_meets_floor(sys.executable):
        return sys.executable
    return ""


def host_orientation_line() -> str:
    """``Host: OS=<sys>; python3=<yes|no> python=<yes|no> (<interpreter-hint>)``,
    with ``py=<yes|no>`` after them when neither bare name answers.

    The trailing parenthetical is DERIVED from the same has_py3/has_py booleans as the
    python3=/python= fields, so it can never contradict them (a fixed literal used to
    claim ``both present`` even on a single-interpreter host).

    ``yes`` means IDENTITY, not presence: a name that resolves but does not answer
    as Python 3 reports ``no``. Reporting ``python=yes`` for a Store App Execution
    Alias put a false host fact into every subagent's orientation line.

    The launcher (``py -3``) is probed only where neither bare name answers:
    there it is the one spelling that runs (the python.org full installer
    leaves PATH alone by default, and the two names are Store aliases), and
    reporting "no python interpreter detected" sent every session and
    subagent looking for an install the host has. Elsewhere it costs no spawn.
    """
    has_py3 = interpreter_is_python3("python3")
    has_py = interpreter_is_python3("python")
    probe_launcher = not (has_py3 or has_py)
    has_launcher = probe_launcher and interpreter_is_python3(LAUNCHER_SPELLING)
    if has_py3 and has_py:
        hint = "both present => prefer python3"
    elif has_py3:
        hint = "python3 only"
    elif has_py:
        hint = "python only"
    elif has_launcher:
        hint = f"{LAUNCHER_SPELLING} only => use {LAUNCHER_SPELLING}"
    else:
        hint = "no python interpreter detected"
    launcher_field = (
        f" py={'yes' if has_launcher else 'no'}" if probe_launcher else ""
    )
    return (
        f"Host: OS={platform.system() or 'unknown'}; "
        f"python3={'yes' if has_py3 else 'no'} python={'yes' if has_py else 'no'}"
        f"{launcher_field} ({hint})"
    )


# The stack table -- tools/cc/_stack_table.py, one row per stack an adopter
# brings, deployed beside this package (the engine reads its byte copy). The
# source-extension set and the project-manifest read order below are
# projections of it. The import is guarded as `_json_safe`'s is above, and
# wider: this file sits above every hook's crash funnel, and a deployed table
# that is absent, hand-patched into a SyntaxError (an edited copy that lost its
# managed marker is kept as the adopter's by the next upgrade) or older than
# this file (a projection it lacks raises at the first call) must degrade to
# the pinned copies, never take the whole hook layer down at import. The
# degrade is SAID once a session where a root is known (``say_stack_table_fault``:
# the two source gates at their root, ``source_extensions``, and ``repo_name``
# for the reporters): gates running on the pinned copy see no stack the table
# gained after it.


_StackProjections = tuple[
    frozenset[str], tuple[str, ...], frozenset[str], dict[str, tuple[str, ...]],
]


def _read_stack_table() -> tuple[_StackProjections | None, str | None]:
    """``((source extensions, project-manifest names, root manifests and
    lockfiles, test roots by manifest), None)`` read from the table, or
    ``(None, the fault)`` for any failure at the import or the first call --
    a deployed table older than this file lacks a projection and raises at
    the call, the degrade documented above -- and for an empty projection,
    which no table yields."""
    try:
        import _stack_table  # noqa: E402

        extensions = frozenset(_stack_table.source_extensions())
        manifests = tuple(row.manifests[0] for row in _stack_table.stacks_with_a_test_command())
        root_files = frozenset(_stack_table.manifest_names()) | frozenset(_stack_table.lockfile_owners())
        test_dirs = dict(_stack_table.test_dirs_by_manifest())
    # fail-open: ok deliberate -- no root is known at import; source_extensions says the fault once a session where one is
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {os_error_text(exc)}"
    if not extensions or not manifests or not root_files or not test_dirs:
        return None, "the table projected an empty set"
    return (extensions, manifests, root_files, test_dirs), None


_STACK_TABLE, _STACK_TABLE_FAULT = _read_stack_table()

# The pinned copies of the two projections the hook layer runs on when the
# table cannot be read: today's table, held equal to it by
# tests/test_stack_table.py. Never empty -- an empty source set would under-arm
# every source gate, and scripts/verify_pins.py refuses to read one as a measurement.
# stack-table: ok purpose-scoped -- the import fallback, held equal to the table by test
_SOURCE_LANGUAGE_FALLBACK = frozenset({
    ".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts",
    ".astro", ".vue", ".svelte",
    ".go", ".rs", ".java", ".kt", ".scala", ".cs", ".cpp", ".c", ".h",
    ".php", ".rb", ".swift",
})
# stack-table: ok purpose-scoped -- the import fallback, held equal to the table by test
_PROJECT_MANIFEST_FALLBACK = ("pyproject.toml", "package.json", "go.mod", "Cargo.toml")
# stack-table: ok purpose-scoped -- the import fallback, held equal to the table by test
_STACK_ROOT_FALLBACK = frozenset({
    "pyproject.toml", "requirements.txt", "setup.py", "setup.cfg", "Pipfile",
    "package.json", "go.mod", "Cargo.toml", "pom.xml", "build.gradle", "Gemfile",
    "package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock",
    "bun.lock", "bun.lockb", "go.sum", "Cargo.lock", "Gemfile.lock",
})

# stack-table: ok purpose-scoped -- the import fallback, held equal to the table by test
_TEST_DIRS_FALLBACK: dict[str, tuple[str, ...]] = {
    "pyproject.toml": ("tests/", "test/"), "requirements.txt": ("tests/", "test/"),
    "setup.py": ("tests/", "test/"), "setup.cfg": ("tests/", "test/"), "Pipfile": ("tests/", "test/"),
    "package.json": ("test/", "tests/", "__tests__/", "spec/"),
    "go.mod": (), "Cargo.toml": ("tests/",), "pom.xml": (), "build.gradle": (), "Gemfile": (),
}

# Every manifest and lockfile in the table: a root-level one is plan-gated
# (plan_guard.PLAN_REQUIRED_ROOT_FILES reads this), since each is the file a
# stack's dependency or build state lives in.
STACK_ROOT_FILES: frozenset[str] = _STACK_TABLE[2] if _STACK_TABLE is not None else _STACK_ROOT_FALLBACK

# Manifest name to the test roots of its stack: the roots the plan guard
# exempts on a tree whose root carries that manifest (``stack_test_roots``).
STACK_TEST_DIRS: dict[str, tuple[str, ...]] = (
    _STACK_TABLE[3] if _STACK_TABLE is not None else _TEST_DIRS_FALLBACK
)

# Ordered core project-manifest filenames: the first manifest of each stack
# that owns a test command, in the table's row order. Single owner for the
# name list that reflect_trigger.CONFIG_FILES (as a set, plus settings.json)
# and repo_name both consume. NOT analyze.MANIFEST_NAMES -- that is the
# package-root marker set (every manifest, pom.xml and build.gradle among
# them) and stays separate.
PROJECT_MANIFEST_NAMES = _STACK_TABLE[1] if _STACK_TABLE is not None else _PROJECT_MANIFEST_FALLBACK

# MCP tool-name write-verb substrings. Single owner for the membership test that
# post_write_check (its AJ advisory + is_mcp_write gate) and reflect_trigger's
# is_mcp_write gate both run — they must not drift on what counts as an MCP write.
MCP_WRITE_VERB_SUBSTRINGS = ("write", "edit", "create", "patch", "append", "save")

# The record files the hooks read back for a leftover merge-conflict marker:
# the memory file, the forward ledger and its probe roster, repo-relative with
# forward slashes. Single owner for the hook side (post_write_check's write-time
# advisory and session_start's memory digest). A hand copy of
# record_merge.ROSTER, which a hook does not import (the resolver is a heavy
# sibling), and of ci_guard._RECORD_FILES, which imports nothing at all;
# tests/test_hooks.py::TestPostWriteCheckRecordFileMarkers pins the copies equal.
RECORD_FILES: tuple[str, ...] = (
    "ESPALIER_MEMORY.md",
    "task-packs/FORWARD_LEDGER.md",
    "task-packs/LEDGER_PROBES.json",
)
# Git's conflict-marker heads at the default marker size: the opener, the
# separator, the closer and diff3's base line. Built, not written, so no marker
# line sits in this file. The same four live in ci_guard (its own copy) and in
# record_merge (_MARK_OURS, _MARK_BASE, _MARK_SEP, _MARK_THEIRS, read by the
# resolver's own stricter rule); the parity test pins the sets equal.
CONFLICT_MARKER_HEADS: tuple[str, ...] = ("<" * 7, "=" * 7, ">" * 7, "|" * 7)


def conflict_marker_lines(text: str) -> list[tuple[int, str]]:
    """``(line_number, head)`` for every line of ``text`` that opens with a
    conflict marker: the first seven characters one of the heads, followed by
    a space or the end of the line, which is ``git diff --check``'s own
    leftover-marker rule. One-based, so a finding reads like a compiler's; a
    prefix test, never a regex; ``splitlines`` reads a CRLF line without its
    carriage return, so a Windows checkout and a POSIX one see the same lines.
    A line that only quotes a marker (a fenced example) is read as one too:
    the escape hatch is column zero, so a quote is indented by one space. The
    twin of ``ci_guard._conflict_marker_lines``, which imports nothing; the
    parity test drives both on one vector."""
    out: list[tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        head = line[:7]
        if head in CONFLICT_MARKER_HEADS and (len(line) == 7 or line[7] == " "):
            out.append((lineno, head))
    return out

# Source-language file extensions -- the shared "what is source code" core that
# reflect_trigger (auto-reflect tracking) and plan_guard (root plan-gating) must
# agree on: every row's source suffixes in the stack table (the guarded read
# above). plan_guard layers .hpp + config extensions on top. The engine's
# analyze.SUFFIX_TO_LANGUAGE is the same table's projection across the
# no-import boundary (tests/test_forced_copy_parity.py pins the two). The
# ES-module and TypeScript-module spellings and the single-file component
# formats joined on 2026-10-06: a Node or Astro tree written in them never
# armed the write count behind stop_gate's hygiene gates or the root plan
# gate. Decided and written down rather than appended: `.mdx` is documentation
# (subagent_stop reads it as docs evidence for Gate 2) and `.css` is styling,
# so neither counts toward the write count. An adopter adds their own with
# espalier.toml's `source_extensions` (``source_extensions`` below), never by
# editing the table's deployed copy.
SOURCE_LANGUAGE_EXTENSIONS = _STACK_TABLE[0] if _STACK_TABLE is not None else _SOURCE_LANGUAGE_FALLBACK

#: An adopter-declared source extension: a dot, then a letter or digit, then
#: letters, digits, dots, underscores or dashes. Twinned in espalier/config.py.
_EXTENSION_SHAPE = re.compile(r"^\.[a-z0-9][a-z0-9._-]*$")
#: An adopter-declared dependency directory: one path component, so no
#: separator, and not the two names every directory answers to. Twinned in
#: espalier/config.py.
_DEPENDENCY_DIR_SHAPE = re.compile(r"^(?!\.\.?$)[^/\\]+$")

_SOURCE_EXT_MEMO: dict[str, tuple[tuple[int, int], frozenset[str]]] = {}


def say_stack_table_fault(root: Path, hook: str) -> None:
    """Say, once a session, that the hook layer is running on its pinned copy
    of the stack table (the guarded read above found none it could use).
    Called by the two source gates at their root resolution -- plan_guard's
    root-file branch never reads ``source_extensions`` below, so the voice
    cannot live there alone -- and by ``source_extensions`` for any other
    caller. Nothing to say when the table read. Never raises (``say_once``)."""
    if _STACK_TABLE is not None:
        return
    say_once(
        root, "stack-table-unreadable", hook, "hook_layer_failed_open_stack_table",
        f"tools/cc/_stack_table.py could not be read ({_STACK_TABLE_FAULT}); the source "
        "extensions, the project-manifest names and the plan-gated root files are this "
        "file's pinned copy of the table until `espalier upgrade --execute` restores it "
        "(a copy edited past its espalier:managed marker is kept as yours: delete it, "
        "then run the upgrade)",
        fault=str(_STACK_TABLE_FAULT),
    )


def source_extensions(root: Path, *, hook: str) -> frozenset[str]:
    """``SOURCE_LANGUAGE_EXTENSIONS`` plus the extensions ``<root>/espalier.toml``
    adds under the flat top-level ``source_extensions`` key (``[".astro",
    ".liquid"]``), lower-cased. Additive only: nothing an adopter writes
    removes a shipped extension. An edit to the file is seen on the next call
    (the parse is memoised on the file's mtime and size, as
    ``adopter_protected_prefixes`` does, since reflect_trigger asks on every
    write of a non-source file). A value that is not a list of strings, or an
    entry that is not an extension, is ignored and SAID once a session
    (``say_once``, from ``hook``): a setting the user wrote that does nothing
    is the defect. Never raises: plan_guard calls this under its umbrella."""
    say_stack_table_fault(root, hook)
    config_path = (root if isinstance(root, Path) else Path(str(root))) / "espalier.toml"
    try:
        st = config_path.stat()
        stamp: tuple[int, int] | None = (st.st_mtime_ns, st.st_size)
    except OSError:  # fail-open: ok deliberate -- absent or unreadable: the shipped set, and the reader below speaks for an unreadable file
        stamp = None
    memo_key = str(config_path)
    if stamp is None:
        _SOURCE_EXT_MEMO.pop(memo_key, None)
    else:
        hit = _SOURCE_EXT_MEMO.get(memo_key)
        if hit is not None and hit[0] == stamp:
            return hit[1]
    result = _read_source_extensions(root, hook=hook)
    if stamp is not None:
        _SOURCE_EXT_MEMO[memo_key] = (stamp, result)
    return result


def _read_source_extensions(root: Path, *, hook: str) -> frozenset[str]:
    """``source_extensions``' uncached read; see there."""
    def _malformed(text: str) -> None:
        say_once(
            root, "source-ext-toml", hook, "config_zone_ignored",
            f"espalier.toml could not be parsed ({text}); source_extensions adds nothing",
            setting="source_extensions",
        )

    raw = read_toml_string_list(root, "source_extensions", on_error=_malformed)
    if raw is None:
        return SOURCE_LANGUAGE_EXTENSIONS
    if not isinstance(raw, list):
        say_once(
            root, "source-ext-not-a-list", hook, "config_zone_ignored",
            f"espalier.toml: source_extensions must be a list of strings, got "
            f"{type(raw).__name__}; it adds nothing",
            setting="source_extensions",
        )
        return SOURCE_LANGUAGE_EXTENSIONS
    added: set[str] = set()
    for i, entry in enumerate(raw):
        spelled = entry.strip().lower() if isinstance(entry, str) else None
        if spelled is None or not _EXTENSION_SHAPE.match(spelled):
            say_once(
                root, f"source-ext-entry-{i}", hook, "config_zone_ignored",
                f"espalier.toml: source_extensions entry {entry!r} is not an "
                "extension such as \".astro\"; ignored",
                setting="source_extensions",
            )
            continue
        added.add(spelled)
    return SOURCE_LANGUAGE_EXTENSIONS | frozenset(added)


def declared_dependency_dirs(root: Path, *, hook: str) -> frozenset[str]:
    """The directory names ``<root>/espalier.toml`` adds under the flat
    top-level ``dependency_dirs`` key (``["deps", "third_party"]``), stripped
    and as written otherwise -- a name matches the directory's spelling on
    disk, on every walk alike, so ``"Deps"`` does not prune ``deps/`` and the
    eight walks give one answer. Additive only: the stack table's own names
    (``node_modules`` and its siblings) are read from the table by each walk,
    never from here, so nothing an adopter writes removes one. The reader for
    the two tools/cc walkers (the router walk, the sister-site probe), each
    called once per run, so the parse is not memoised as ``source_extensions``'
    is. A value that is not a list of strings, or an entry that is not a
    directory name (a separator, ``.`` or ``..``), is ignored and SAID once a
    session (``say_once``, from ``hook``). Never raises."""
    def _malformed(text: str) -> None:
        say_once(
            root, "dependency-dirs-toml", hook, "config_zone_ignored",
            f"espalier.toml could not be parsed ({text}); dependency_dirs adds nothing",
            setting="dependency_dirs",
        )

    raw = read_toml_string_list(root, "dependency_dirs", on_error=_malformed)
    if raw is None:
        return frozenset()
    if not isinstance(raw, list):
        say_once(
            root, "dependency-dirs-not-a-list", hook, "config_zone_ignored",
            f"espalier.toml: dependency_dirs must be a list of strings, got "
            f"{type(raw).__name__}; it adds nothing",
            setting="dependency_dirs",
        )
        return frozenset()
    added: set[str] = set()
    for i, entry in enumerate(raw):
        name = entry.strip() if isinstance(entry, str) else None
        if name is None or not _DEPENDENCY_DIR_SHAPE.match(name):
            say_once(
                root, f"dependency-dirs-entry-{i}", hook, "config_zone_ignored",
                f"espalier.toml: dependency_dirs entry {entry!r} is not a directory "
                "name such as \"deps\" (one component, no separator); ignored",
                setting="dependency_dirs",
            )
            continue
        added.add(name)
    return frozenset(added)


def repo_name(root: Path, *, warn_label: str) -> str:
    """Repo name from pyproject.toml / package.json / Cargo.toml / go.mod, else dir name.

    Hoisted from the byte-near-identical _repo_name in session_start.py and
    post_compact.py (they differed only in comment wording + the warn_exc
    prefix). ``warn_label`` is that prefix, so each caller keeps its own
    observable warn line -- and names the hook when the manifest order it
    reads is the pinned copy of the stack table, so a reporter-only turn
    (SessionStart, PostCompact) says the fault too.
    """
    say_stack_table_fault(root, warn_label)
    for config in PROJECT_MANIFEST_NAMES:
        config_path = root / config
        if not config_path.exists():
            continue
        try:
            content = config_path.read_text(encoding="utf-8", errors="replace")
            if config == "package.json":
                # A valid-JSON non-dict package.json (`[]`) would crash
                # data.get → hook exit 1 → context dropped. Guard the deref; a
                # *malformed* package.json still warns via the JSONDecodeError
                # handler below (observability preserved).
                data = json.loads(content)
                if isinstance(data, dict):
                    name = data.get("name")
                    if isinstance(name, str) and name:
                        return name
                return root.name
            for line in content.splitlines():
                if line.strip().startswith("name"):
                    parts = line.split("=", 1) if "=" in line else line.split(":", 1)
                    if len(parts) == 2:
                        return parts[1].strip().strip('"').strip("'").strip(",")
        except json.JSONDecodeError as e:
            # voice: debug-log a malformed manifest costs only the name, which falls back to the directory's
            warn_exc(f"{warn_label}: malformed {config}", e)
        except OSError:
            pass
    return root.name


def check_branch(root: Path) -> str:
    """Current git branch, or 'detached HEAD' / 'unknown' on degrade.

    Hoisted byte-identical from session_start._check_branch and
    post_compact._check_branch.
    """
    import subprocess  # deferred: per-tool-call hooks never call check_branch

    try:
        result = subprocess.run(  # spawn: ok a session-start reporter; a git that cannot run costs the branch line, never the banner
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5, cwd=str(root),
        )
        branch = result.stdout.strip()
        return branch if branch else "detached HEAD"
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return "unknown"


def surface_status(root: Path, *, degraded_format: str = "upper") -> str:
    """Verify core harness infrastructure exists; report 'healthy' or a degraded line.

    Hoisted from session_start._check_surface and post_compact._surface_status
    — same checks, divergent user-facing string. ``degraded_format`` preserves
    both verbatim:
      'upper'  -> "DEGRADED: missing CLAUDE.md, ..."   (session_start)
      'paren'  -> "degraded (missing: CLAUDE.md, ...)" (post_compact)
    """
    # `os.path.exists`, never `Path.exists()`: PostCompact and SessionStart
    # run this mid-session, after the operator may have changed permissions,
    # and a `.claude` that denies traversal made pathlib raise out of the
    # hook on CPython 3.10-3.13 (the whole re-injection lost) while 3.14
    # read it as absent (DEF-763). `os.path` answers "missing" on every
    # interpreter, which is the honest degraded line here.
    missing = []
    if not os.path.exists(root / "CLAUDE.md"):
        missing.append("CLAUDE.md")
    if not os.path.exists(root / ".claude" / "settings.json"):
        missing.append(".claude/settings.json")
    if not os.path.exists(root / "tools" / "cc"):
        missing.append("tools/cc/")
    if not missing:
        return "healthy"
    joined = ", ".join(missing)
    if degraded_format == "paren":
        return f"degraded (missing: {joined})"
    return f"DEGRADED: missing {joined}"


STOP_GATE_DEFAULT_MODE = "light"


def stop_gate_mode(raw: str | None, default: str = STOP_GATE_DEFAULT_MODE) -> str:
    """Canonical normalization for the stop-gate mode env value.

    THE single grammar. Five readers each parsed the same variable differently
    -- ``.strip().lower()`` + a recognized set, a raw ``!= "full"``, ``.lower()``
    alone, ``or "light"`` on the raw value, and a raw ``!= "light"`` -- so a
    space-padded value ran the FULL pytest suite on every Stop while the
    statusline showed no indicator and the dormancy note never fired. Divergence
    in five spellings of one decision is the class; this is the one spelling.

    Takes the raw value rather than reading the environment itself, so each
    caller keeps its own env-name constant where the constant-parity gate
    (tests/test_hook_constant_parity.py) can still see the literal. Returns
    ``default`` for None/empty/whitespace-only -- never an empty mode, which a
    membership test would silently read as "unset".

    Recognized-set validation and the unknown-value warning stay in stop_gate:
    they are that hook's policy, not shared vocabulary, and importing its
    ``warn`` into every reader would drag the Stop tier into advisory hooks.
    """
    return (raw or "").strip().lower() or default


def plural(n: int, singular: str, plural_form: str | None = None) -> str:
    """Return a ``"<n> <word>"`` string, pluralizing ``word`` on count.

    ``singular`` when ``n == 1``, else ``plural_form`` (default: ``singular``
    + ``"s"``). Renders the count too: ``plural(1, "warning")`` -> ``"1
    warning"``; ``plural(2, "warning")`` -> ``"2 warnings"``; ``plural(0,
    "file")`` -> ``"0 files"``. Pass ``plural_form`` for irregular plurals
    (e.g. ``plural(n, "entry", "entries")``).

    Intentional duplicate of ``espalier._text.plural`` — ``tools/cc/`` cannot
    import ``espalier`` (the zero-espalier-import contract), so the standalone
    hook copy stands alone. Do NOT dedup the two.
    """
    word = singular if n == 1 else (plural_form or f"{singular}s")
    return f"{n} {word}"
