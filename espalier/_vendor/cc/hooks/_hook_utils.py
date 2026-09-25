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
import stat
import sys
import unicodedata
from collections.abc import Callable, Iterator
from pathlib import Path

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
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return False
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
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
    Git Bash -- ``CLAUDE_PROJECT_DIR=$(pwd)`` gives ``/c/Users/<u>/repo`` there,
    which is how walk 2 drove the hooks -- is rooted but drive-less to
    ``ntpath``, so ``Path(raw).resolve()`` anchored it onto the current drive
    as the fabricated ``C:\\c\\Users\\<u>\\repo``. Against THAT root the
    untranslated leaf happened to relativise (both sides fabricated alike) and
    a translated leaf cannot, so translating the leaf alone would have turned
    a lucky DENY into an ALLOW: both sides of the compare translate, the way
    ``_bash_patterns._posix`` already treats target and root alike. Split
    from ``resolve_project_root`` so the translation is pinned on a POSIX
    test host without constructing a ``WindowsPath``. A native
    ``C:\\Users\\...`` value passes through untouched.
    """
    raw = os.environ.get("CLAUDE_PROJECT_DIR")
    if raw is None or raw == "":
        if raw == "":
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
    """
    print(f"[WARN] espalier: {msg}", file=sys.stderr)


def warn_exc(prefix: str, exc: Exception) -> None:
    """Emit a terse warning with exception class and message. No traceback.
    An ``OSError``'s path is rendered as a path, not through ``repr``
    (``os_error_text``; DEF-799) -- the one place the hooks' handlers hand an
    exception to for rendering, so it is the one place that has to know."""
    print(f"[WARN] espalier: {prefix}: {type(exc).__name__}: {os_error_text(exc)}", file=sys.stderr)


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
    except ImportError:
        # The mirror lives in the same directory as _hook_utils.py;
        # if it's missing the hook can't verify the pin, so deny the
        # signal (safer default: treat as user-repo).
        return False
    path = root / "tools" / "cc" / "hooks" / "write_guard.py"
    if not path.is_file():
        return False
    try:
        prefix = path.read_bytes()[: _self_host_fingerprint.WRITE_GUARD_PREFIX_BYTES]
    except OSError:
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
    except (OSError, UnicodeDecodeError):
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


def harness_exempt_prefixes(root: Path) -> list[str]:
    """Prefixes plan_guard exempts from plan-required check.

    On a user repo, espalier/ is potentially user code, so plan discipline
    applies. On self-host, espalier/ is our source — same exempt logic as
    the rest of the harness internals.
    """
    universal = list(EXEMPT_UNIVERSAL_PREFIXES)
    if is_self_host_repo(root):
        return universal + ["espalier/"]
    return universal


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
    except (OSError, ValueError):
        return False
    if not text.strip():
        return False
    return any(
        not is_seeded_placeholder(title, body)
        for title, body in iter_doc_sections(text)
    )


# ── Safe stdin reading (BOM + UTF-8 sweep) ───────────────────────────────────


def read_stdin_safely() -> dict:
    """Read a JSON object from stdin; return ``{}`` on any failure.

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
    except (OSError, ValueError, AttributeError):
        return {}
    if not raw:
        return {}
    try:
        text = raw.decode("utf-8-sig", errors="replace")
    except (UnicodeDecodeError, LookupError):
        return {}
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


# ── Atomic write ─────────────────────────────────────────────────────────────

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
        os.replace(tmp_path, path)
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
# The one hand-written relief record both gates honour: ``agent`` is this value
# and ``note`` says why. A judgement the operator is recording, not a gate being
# skipped -- the deny messages name it, stop_gate announces its use on stderr
# (observable in the transcript, like a maintenance-mode bypass), and a note
# shorter than the floor is a word, not a judgement.
OPERATOR_RELIEF_AGENT = "operator"
OPERATOR_RELIEF_NOTE_MIN_CHARS = 20

# Cold-open baton flag. SessionStart (producer) drops it on a new-session source;
# task_router (consumer) reads-and-deletes it on the session's first prompt to
# enforce an un-preemptible orientation readout. Named HERE — the one module both
# standalone hooks already import — so the producer and consumer can never drift on
# the literal (the parity problem, avoided by sharing instead of duplicating).
COLD_OPEN_FLAG = "cold_open_pending"

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


def _read_counter(state_dir: Path, name: str = COUNTER_FILE) -> int:
    """Read the named counter (defaults to ``write_count``). The ``name`` param
    lets the same reader serve ``tool_call_count`` too."""
    counter_path = state_dir / name
    if not counter_path.exists():
        return 0
    try:
        return int(counter_path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
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


def _locked_increment(state_dir: Path, name: str = COUNTER_FILE) -> int:
    """Atomically read-modify-write the counter.

    A naive ``count = _read_counter() + 1; _write_counter(count)`` is a
    classic TOCTOU: two parallel CC sessions both read N, both write
    N+1, the counter drifts by half. The reflect-every-10th-write
    cadence depends on the counter being monotonic across sessions,
    so the drift breaks the trigger semantics for users running CC in
    a parent repo + worktree simultaneously.

    Mechanism: ``fcntl.flock`` on POSIX gives advisory exclusion across
    processes. The lock is taken on the counter file's own file
    descriptor — opening the file in r+/append mode and locking the
    fd is safe under concurrent openers. On Windows ``fcntl`` is
    absent; we fall through and accept the (smaller) Windows race —
    Windows operators rarely run two CC sessions in one repo, and
    adding a Win32 lock would require importing ``msvcrt`` with
    different ergonomics. Audit + docs note this as a known limit.

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
    except OSError:
        # Read-only state dir — can't persist; degrade to best-effort read.
        return _read_counter(state_dir)
    try:
        import fcntl  # POSIX only
    except ImportError:
        # Windows fallback — atomic write (temp + os.replace) but the RMW is
        # non-serialized, and os.replace over an open reader handle can raise
        # PermissionError, so the empty-read window is closed on POSIX only
        # (documented limit).
        current = _read_counter(state_dir, name)
        new = current + 1
        try:
            _write_counter(state_dir, new, name)
        except OSError:
            return current
        return new
    # POSIX: serialize the read-modify-write across processes on a STABLE
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
        with open(lock_path, "a+", encoding="utf-8") as lock_fh:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
            try:
                current = _read_counter(state_dir, name)
                new = current + 1
                _write_counter(state_dir, new, name)
            finally:
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
        return new
    except OSError:
        # flock-less FS (some NFS / network mounts) or open failure on a
        # now-unwritable file — degrade to best-effort read, no crash.
        return _read_counter(state_dir, name)


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
    except (OSError, ValueError):
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
    the write is serialized under an ``fcntl.flock`` on a STABLE sibling lock
    file (mirroring ``_locked_increment`` above). Two concurrent hooks — a parent
    repo and a git worktree sharing one ``.espalier-state`` — could otherwise
    interleave one record into a malformed JSONL line.

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
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(line)

        try:
            import fcntl  # POSIX only
        except ImportError:
            _append()  # Windows: best-effort unlocked append (documented limit)
            return
        # Acquire the lock in its OWN try so the unlocked fallback fires ONLY when
        # lock acquisition fails (flock-less FS / unwritable lock) — never as a
        # retry of a mid-write append, which would double-append a torn record.
        lock_fh = None
        try:
            lock_fh = open(state_dir / (name + ".lock"), "a+", encoding="utf-8")
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
        except OSError:
            if lock_fh is not None:
                lock_fh.close()
            _append()
            return
        try:
            _append()
        finally:
            try:
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
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
#: ``/c/Users/<u>`` is ``C:\Users\<u>`` -- and that is what the Bash tool's own
#: ``pwd`` returns on Windows, so any path an agent builds from ``pwd``, ``$PWD``
#: or a parent-directory move arrives in it. Neither ``pathlib`` nor ``ntpath``
#: knows the spelling: to them a rooted, drive-less path is not absolute, so
#: joining it onto a drive root fabricates ``C:/c/Users/<u>`` and every compare
#: against the drive-spelled home or repo root misses (DEF-731, walk 2 finding
#: 11: the home directory fell to the clearable delete tier, and a protected
#: write in the same spelling matched no zone). Anchored, one letter, then a
#: separator or the end -- ``/cygdrive/c``, ``/tmp`` and ``//server/share`` do
#: not match. No quantifier, so nothing to backtrack.
_MSYS_DRIVE_RE = re.compile(r"^/([A-Za-z])(?=/|$)")


def _msys_drive_to_windows(path: str) -> str:
    """Translate a Git Bash drive prefix to its Windows form, on Windows only.

    ``/c/Users/x`` -> ``C:/Users/x``; ``/c`` and ``/c/`` -> ``C:/``, the drive
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
    * **Translate a Git Bash drive prefix** (``/c/x`` → ``C:/x``, Windows only;
      ``_msys_drive_to_windows``) before anything reads the path as absolute
      or joins it to root. After the ``file://`` strip so ``file:///c/x``
      lands in the same form; before ``~`` expansion, which never yields one.
    * **Fold separators AGAIN after ``~`` expansion.** ``ntpath.expanduser``
      splices ``USERPROFILE`` in as spelled -- ``C:\\Users\\<u>`` + ``/repo/...``
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
    case-insensitive, so ``/users/...`` and ``/Users/...`` name the SAME
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
    except (OSError, ValueError):
        return None
    line = lines[0].strip() if lines else ""
    if not line.startswith("gitdir:"):
        return None
    target = line[len("gitdir:"):].strip()
    if not target:
        return None
    try:
        return (checkout / target).resolve()
    except (OSError, ValueError):
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
    except (OSError, ValueError, NotImplementedError):
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
    except (OSError, ValueError, NotImplementedError):
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
    except (OSError, ValueError, NotImplementedError):
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
    except (ValueError, OSError):
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
        except (OSError, ValueError):
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
    # A Git Bash drive spelling (`/c/Users/x`) is absolute on the host that
    # produces it, and `Path` on Windows anchors it onto the current drive as
    # `C:\\c\\Users\\x` -- a directory that is not there -- so the walk read
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
    """
    if not name_or_path:
        return False
    if name_or_path in _INTERPRETER_IDENTITY_MEMO:
        return _INTERPRETER_IDENTITY_MEMO[name_or_path]
    import shutil
    import subprocess
    resolved = shutil.which(name_or_path) or (
        name_or_path if Path(name_or_path).is_file() else None
    )
    verdict = False
    if resolved:
        # See the engine-side twin: never spawn a probe for the interpreter
        # already running this code. Removes the spawn AND the false alarm on a
        # host where spawning is blocked.
        try:
            if os.path.samefile(resolved, sys.executable):
                _INTERPRETER_IDENTITY_MEMO[name_or_path] = True
                return True
        except OSError:
            pass
        try:
            result = subprocess.run(
                [resolved, "--version"], capture_output=True, text=True,
                encoding="utf-8", timeout=2,
            )
            # Through the ONE banner rule (`is_python3_banner`), not
            # `startswith("Python 3.")`: the floor parser searches anywhere in
            # the output, and a banner with a line before it made identity and
            # the floor disagree about one interpreter (DEF-727 review).
            verdict = is_python3_banner((result.stdout or result.stderr).strip())
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


def interpreter_meets_floor(name_or_path: str) -> bool:
    """Does ``name_or_path`` answer as a Python that clears :data:`MIN_PYTHON`?

    The capability sibling of :func:`interpreter_is_python3`. Use this wherever
    a DECISION is made -- warn about a wired interpreter, refuse to wire one --
    and the identity probe only where a host FACT is being reported.

    A stock ``/usr/bin/python3`` on macOS is 3.9.6: identity True, floor False.
    That gap is the entire defect this pair was split to express (``DEF-636``);
    before the floor existed there was only the identity question, and it was
    answering the capability one by accident.
    """
    if not name_or_path:
        return False
    key = ("floor", name_or_path)
    if key in _INTERPRETER_IDENTITY_MEMO:
        return _INTERPRETER_IDENTITY_MEMO[key]
    import shutil
    import subprocess
    resolved = shutil.which(name_or_path) or (
        name_or_path if Path(name_or_path).is_file() else None
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
            result = subprocess.run(
                [resolved, "--version"], capture_output=True, text=True,
                encoding="utf-8", timeout=2,
            )
            verdict = meets_python_floor((result.stdout or result.stderr).strip())
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
    for candidate in ("python3", "python"):
        if interpreter_meets_floor(candidate):
            return candidate
    if sys.executable and interpreter_meets_floor(sys.executable):
        return sys.executable
    return ""


def host_orientation_line() -> str:
    """``Host: OS=<sys>; python3=<yes|no> python=<yes|no> (<interpreter-hint>)``.

    The trailing parenthetical is DERIVED from the same has_py3/has_py booleans as the
    python3=/python= fields, so it can never contradict them (a fixed literal used to
    claim ``both present`` even on a single-interpreter host).

    ``yes`` means IDENTITY, not presence: a name that resolves but does not answer
    as Python 3 reports ``no``. Reporting ``python=yes`` for a Store App Execution
    Alias put a false host fact into every subagent's orientation line.
    """
    has_py3 = interpreter_is_python3("python3")
    has_py = interpreter_is_python3("python")
    if has_py3 and has_py:
        hint = "both present => prefer python3"
    elif has_py3:
        hint = "python3 only"
    elif has_py:
        hint = "python only"
    else:
        hint = "no python interpreter detected"
    return (
        f"Host: OS={platform.system() or 'unknown'}; "
        f"python3={'yes' if has_py3 else 'no'} python={'yes' if has_py else 'no'} "
        f"({hint})"
    )


# Ordered core project-manifest filenames. Single owner for the name list that
# reflect_trigger.CONFIG_FILES (as a set, plus settings.json) and repo_name both
# consume. NOT analyze.MANIFEST_NAMES — that is a forced cousin (adds pom.xml /
# build.gradle for language fingerprinting) and stays separate.
PROJECT_MANIFEST_NAMES = ("pyproject.toml", "package.json", "Cargo.toml", "go.mod")

# MCP tool-name write-verb substrings. Single owner for the membership test that
# post_write_check (its AJ advisory + is_mcp_write gate) and reflect_trigger's
# is_mcp_write gate both run — they must not drift on what counts as an MCP write.
MCP_WRITE_VERB_SUBSTRINGS = ("write", "edit", "create", "patch", "append", "save")

# Source-language file extensions — the shared "what is source code" core that
# reflect_trigger (auto-reflect tracking) and plan_guard (root plan-gating) must
# agree on. plan_guard layers .hpp + config extensions on top; keeping the
# language set single-sourced here prevents the two from drifting (a root
# .rb/.swift edit that was reflect-tracked but NOT plan-gated). NOT
# analyze.SUFFIX_TO_LANGUAGE — that is a forced fingerprint cousin with no config
# keys and stays separate.
SOURCE_LANGUAGE_EXTENSIONS = frozenset({
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".go", ".rs", ".java", ".rb", ".php",
    ".cpp", ".c", ".h", ".cs", ".swift",
    ".kt", ".scala",
})


def repo_name(root: Path, *, warn_label: str) -> str:
    """Repo name from pyproject.toml / package.json / Cargo.toml / go.mod, else dir name.

    Hoisted from the byte-near-identical _repo_name in session_start.py and
    post_compact.py (they differed only in comment wording + the warn_exc
    prefix). ``warn_label`` is that prefix, so each caller keeps its own
    observable warn line.
    """
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
        result = subprocess.run(
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
