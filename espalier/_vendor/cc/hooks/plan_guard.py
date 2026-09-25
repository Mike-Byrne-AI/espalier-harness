#!/usr/bin/env python3
"""PreToolUse hook — blocks source file writes without an active execution plan.

Exemptions: see the EXEMPT_PREFIXES tuple below — deliberately NOT restated
here. The enumeration this line used to carry went stale (it omitted memory/
and docs/ from the moment those were added, and listed espalier/ flatly when
espalier/ is exempt only on the self-host repo), which is the drift the tuple's
own derived gates exist to prevent.
Root-level files are exempt only when they are not known source/config/project
files (e.g. ESPALIER_MEMORY.md is exempt; README.md and pyproject.toml require a plan).

Bash/PowerShell: write-intent detection runs BEFORE the read-only allowlist so
commands such as "echo x > src/x.py" or "python -c open(f,w)" are caught even
though their first token looks read-only.

Exit 0 + permissionDecision="deny" = block (source write without plan).
Exit 0 with no JSON = allow.
Never crashes on malformed input (always exits 0 on error).

POST-TP-64 NOTICE
=================
The Bash/PowerShell/MCP branches in main() are NEVER reached at runtime.
.claude/settings.json matches this hook on Write|Edit|NotebookEdit only
(see espalier.harness_config.CANONICAL_HOOK_WIRING). The branches and the
bash_has_write_intent / _mcp_tool_is_write helpers are retained as
importable classifiers for external scripts (e.g. custom hooks, audit
tooling) and as defense-in-depth if the matcher is ever widened. Coverage
of Bash mutations of protected zones (a write into, a delete of, a move out
of a zone) lives in write_guard.py.

Contract: tests/test_plan_guard_branch_pinned.py pins:
  - the CANONICAL_HOOK_WIRING matcher value (Write|Edit|NotebookEdit)
  - the presence of this banner string (POST-TP-64 NOTICE sentinel)
  - the presence of the dead branches in main()

If you widen the matcher AND delete the branches in the same change, the
pin test fires.
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata  # NFKC + casefold for Unicode-equivalent paths
from pathlib import Path

# Co-located helper module — same zero-espalier-import pattern as other hooks.
sys.path.insert(0, str(Path(__file__).parent))
import _denial_reasons  # noqa: E402
import _hook_utils  # noqa: E402
import _integrity  # noqa: E402
import _maintenance_mode  # noqa: E402
from _hook_utils import os_error_text  # noqa: E402

# stdlib TOML for adopter-configured exempt prefixes. The
# zero-espalier-imports contract forbids reaching into espalier/_compat.py,
# so this mirrors that file's fallback pattern inline.
try:
    import tomllib as _tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:
    try:
        import tomli as _tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:
        _tomllib = None  # type: ignore[assignment]

# Bash/PowerShell dispatch in main() dead under current matcher; see header banner.
# Shared SoT via _hook_utils.MUTATION_TOOLS.
MUTATION_TOOLS = _hook_utils.MUTATION_TOOLS

# Paths exempt from plan requirement (prefix match, normalized)
# Universal exempt prefixes — paths under these don't require an active
# plan regardless of repo context. On the self-host repo, _is_exempt() also
# treats `espalier/` as exempt via _hook_utils.harness_exempt_prefixes().
# Tests that pin the universal contract import this constant directly (e.g.,
# test_contracts.py). This literal MIRRORS the single owner
# _hook_utils.EXEMPT_UNIVERSAL_PREFIXES (the operative source harness_exempt_prefixes
# derives from); test_forced_copy_parity binds the two as sets so they cannot drift.
# Kept as an AST-parseable literal here because test_contracts.py AST-walks it.
#
# Critical: a user repo with its own `espalier/` directory MUST NOT skip
# plan discipline — that would silently disable the gate for user code.
# sister-site: ok purpose-scoped: plan-exempt policy (OMITS espalier/); distinct from reflect_trigger.EXCLUDED_PREFIXES
EXEMPT_PREFIXES = (
    "tests/",
    "tools/cc/",
    ".claude/",
    "cc/",
    "reports/",
    # §C23: the harness's own commands, skills and gate messages instruct writes
    # here, at moments when no plan is active by construction. `memory/` — the
    # deployed reflect skill's memory-promotion write and /handoff's routing, both
    # at status='complete'. `docs/` — stop_gate Gate 2 orders a docs-maintainer
    # run. `task-packs/` — the seeded docs/PACK_AUTHORING.md walks an adopter
    # through authoring `task-packs/TP-N-your-pack.md`, and /implement-pack later
    # moves the landed file into `task-packs/Done/`; pack authoring precedes any
    # plan by construction, since the pack IS the plan. Denying any of the three
    # made the harness block the workflow it prescribes.
    # Pinned by tests/test_contracts.py::TestPlanGuardExemptsPrescribedWrites,
    # which DERIVES the prescribed-write set rather than restating this tuple —
    # by TWO independent routes, because the prose arm alone missed `task-packs/`
    # on all three of population, verb vocabulary and path recognition.
    #
    # ACCEPTED over-reach, considered rather than overlooked: these are bare
    # prefixes, so an adopter who already owns a `task-packs/` holding real
    # source loses plan discipline there. Same shape as the logged `reports/`
    # instance (in the since-retired findings corpus) and accepted for the same reason —
    # a narrower rule would have to guess which files in a directory the
    # harness routes them into are "really" theirs, and guessing wrong denies
    # the prescribed write, which is the defect this exemption exists to fix.
    "memory/",
    "docs/",
    "task-packs/",
    # The hooks' own state dir: the hygiene gates' deny messages ask for a
    # relief record written there by hand, at Stop time, when no plan is active
    # by construction. Mirrors _hook_utils.EXEMPT_UNIVERSAL_PREFIXES.
    ".espalier-state/",
)

# Root-level filenames that always require a plan regardless of extension
PLAN_REQUIRED_ROOT_FILES = frozenset({
    "Dockerfile", "Makefile", "Procfile",
    "requirements.txt", "requirements-dev.txt",
    "setup.py", "setup.cfg",
    "README.md", "AGENTS.md", "CLAUDE.md", "CHANGELOG.md", "CONTRIBUTING.md",
})

# Root-level extensions that always require a plan. The source-language core is
# the single owner _hook_utils.SOURCE_LANGUAGE_EXTENSIONS — so a root .rb/.php/
# .cs/.swift/.kt/.scala edit is plan-gated, not just reflect-tracked (the pre-fix
# under-gating bug). .hpp and the config extensions are the plan-gate-specific
# superset. Pinned ⊇ the source core by test_forced_copy_parity.
PLAN_REQUIRED_ROOT_EXTENSIONS = _hook_utils.SOURCE_LANGUAGE_EXTENSIONS | frozenset({
    ".hpp",
    ".toml", ".yaml", ".yml", ".json", ".ini", ".cfg", ".lock",
})

# Root-source exemption sentinel. `plan_exempt_prefixes` matches via startswith,
# which can never match a bare root-level filename (e.g. "app.py"), so a flat-
# layout adopter had no way to exempt their own source. "./" is the one entry
# that passes prefix validation (ends with "/") yet is otherwise a dead no-op —
# repurpose it as an explicit "exempt root-level source files" opt-in.
_ROOT_SOURCE_SENTINEL = "./"

# Adopter escape hint appended to every plan-required deny. Points to the
# narrow knob (plan_exempt_prefixes in espalier.toml) rather than to
# ESPALIER_MAINTENANCE_MODE, which is scoped for harness self-edits and also
# bypasses write_guard + two stop_gate checks (see CLAUDE.md "Plan Guard"
# section). This closes the discoverability gap that otherwise trains adopters
# into the maintenance-mode escape hatch.
_PLAN_EXEMPT_HINT = (
    " Adopter source roots: set `plan_exempt_prefixes = [\"src/\"]` in "
    "espalier.toml (see CLAUDE.md \"Plan Guard\" section). Do NOT use "
    f"{_maintenance_mode.ENV_VAR} for this — that scope is harness self-edits."
)

# Targeted variant for a denied ROOT-LEVEL source file. A bare root filename
# (e.g. "app.py") can't be covered by a directory prefix, so the generic src/
# hint above would misdirect a flat-layout adopter — point them at the "./"
# sentinel instead. Keeps the literal `plan_exempt_prefixes` + `espalier.toml`
# tokens the deny-reason contract checks for.
_ROOT_SOURCE_HINT = (
    " Root-level source detected: set `plan_exempt_prefixes = [\"./\"]` in "
    "espalier.toml to exempt source files at the repo root. Do NOT use "
    f"{_maintenance_mode.ENV_VAR} for this — that scope is harness self-edits."
)

# Bash/PowerShell commands that are clearly read-only (checked AFTER write-intent)
READONLY_BASH_PATTERN = re.compile(
    r"^\s*(grep|cat|ls|find|git\s+(status|log|diff|show|branch|remote)|"
    r"pytest|python3?\s+-c|echo|head|tail|wc|sort|uniq|less|more|pwd|which|"
    r"python3?\s+\S+\.py\b)",
    re.IGNORECASE,
)

# ── Bash write-intent patterns ────────────────────────────────────────────

# >> file (append redirect) — never an fd redirect when not followed by & or digit
_APPEND_REDIRECT_RE = re.compile(r">>(?![>&\d])\s*\S")

# > file (output redirect) — not preceded by >, &, or digit; not followed by &, >, or digit
_WRITE_REDIRECT_RE = re.compile(r"(?<![>&\d])>(?![>&\d])\s*\S")

# Inherently mutating shell commands.
# Spans are bounded (`.{0,200}`, `\w{0,40}`) to avoid catastrophic backtracking:
# the perl arm's unbounded `.*` was quadratic at hook runtime on a repeated
# `-pppp…` payload (a PreToolUse slow-hook fail-open); the sed arm is bounded
# for consistency. Detection-preserving (`sed -i`, `sed -e x -i`, `perl -pi`,
# `perl -pi -e`, `tee`, `rm` all still match). Pinned by `tests/test_redos.py`'s
# dot-star completeness gate.
_SHELL_MUTATE_RE = re.compile(
    r"^\s*(rm|mv|cp|touch|mkdir|rmdir)\b"
    r"|\btee\b"
    r"|\bsed\b.{0,200}\s-i\b"
    r"|\bperl\b.{0,200}-\w{0,40}p\w{0,40}i\b",
    re.IGNORECASE | re.DOTALL,
)

# Python inline write APIs detected inside python -c strings.
# Uses \x22/\x27 hex escapes for quote chars to avoid delimiter conflicts.
_PYTHON_WRITE_RE = re.compile(
    r"open\s*\([^)]+,\s*[\x22\x27]?[waxWAX]"
    r"|\.write_text\s*\("
    r"|\.write_bytes\s*\("
    r"|\.unlink\s*\("
    r"|\.rename\s*\("
    r"|shutil\.(?:copy|copyfile|move|rmtree)\s*\("
    r"|os\.(?:remove|unlink|rmdir|makedirs|mkdir|rename)\s*\(",
    re.IGNORECASE,
)

#: Unanchored and read off the raw command on purpose: the Bash branch this
#: serves is unreachable under the shipped matcher (see the header), so there
#: is nothing for a `#`-comment mention to trip. If Bash is ever added to this
#: hook's matcher, anchor it the way `_bash_patterns` anchored the
#: interpreter openers (DEF-704, and DEF-712 on the PowerShell leg) before
#: relying on it.
_PYTHON_INLINE_RE = re.compile(r"python3?\s+-c\b", re.IGNORECASE)


# MCP tool-name keywords that indicate file-write intent. Excludes verbs
# (`execute`, `send`, `commit`, `run_`, `post_`) that match common READ /
# network / version-control method names (`mcp__sqlite__execute_query`,
# `mcp__github__post_comment`, `mcp__ci__run_tests`, `mcp__git__commit`) — those
# would produce spurious plan-required denials. Only verbs that UNAMBIGUOUSLY
# indicate filesystem mutation. Conservative false-allow on ambiguous names;
# write_guard is the second line of defense for protected zones.
_MCP_WRITE_VERBS: tuple[str, ...] = (
    "write", "edit", "create_file", "create-file",
    "delete_file", "delete-file", "delete_directory", "delete-directory",
    "remove_file", "remove-file", "remove_directory", "remove-directory",
    "move_file", "move-file", "rename_file", "rename-file",
    "copy_file", "copy-file", "patch_file", "patch-file",
    "append_file", "append-file", "save_file", "save-file",
    "mkdir", "touch",
)


def _mcp_tool_is_write(tool_name: str) -> bool:
    """Return True if the MCP tool name suggests a filesystem mutation.

    Examples (True):  mcp__filesystem__write_file, mcp__filesystem__create_file,
                      mcp__filesystem__move_file, mcp__fs__mkdir.
    Examples (False): mcp__filesystem__read_file, mcp__github__list_issues,
                      mcp__sqlite__execute_query (no file write),
                      mcp__github__post_comment (network, not FS),
                      mcp__ci__run_tests, mcp__git__commit_changes.
    """
    lower = tool_name.lower()
    return any(verb in lower for verb in _MCP_WRITE_VERBS)


# Dispatch in main() dead under current matcher; function remains callable by external scripts; see header banner.
def bash_has_write_intent(command: str) -> bool:
    """Return True if the command appears to write or mutate files.

    Checks redirects, common mutation commands, and Python inline write APIs.
    This is a deterministic command classifier for Claude Code hook events,
    not a hard sandbox. It detects common write forms to require an active plan.
    """
    if _APPEND_REDIRECT_RE.search(command):
        return True
    if _WRITE_REDIRECT_RE.search(command):
        return True
    if _SHELL_MUTATE_RE.search(command):
        return True
    if _PYTHON_INLINE_RE.search(command) and _PYTHON_WRITE_RE.search(command):
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────


def _regex_extract_exempt_prefixes(config_path: Path) -> list | None:
    """Best-effort stdlib fallback for reading ``plan_exempt_prefixes`` when no
    TOML parser is importable (a Python < 3.11 hook interpreter without
    ``tomli``).

    The schema is a flat list of quoted strings, so a small regex recovers it
    without a parser — the adopter's exempt config keeps working on any 3.10
    host instead of being silently dropped on every write. Returns the raw
    string list (which the shared validator below then checks the same way as
    the TOML path), or ``None`` when the top-level key is absent or the file
    can't be read. Degraded mode: full-line ``#`` comments are stripped first,
    but this deliberately does not reimplement TOML — it only recovers the one
    flat key the hook honors. Recovery itself (not just the shared validation
    below) is best-effort and can diverge from a real TOML parse for
    table-scoped or duplicate keys and for quote/bracket characters inside a
    value.
    """
    try:
        text = config_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    text = re.sub(r"(?m)^\s*#.*$", "", text)  # drop full-line comments
    m = re.search(r"plan_exempt_prefixes\s*=\s*\[(.*?)\]", text, re.DOTALL)
    if m is None:
        return None
    return re.findall(r"""["']([^"']*)["']""", m.group(1))


def _load_adopter_exempt_prefixes(root: Path) -> tuple[str, ...]:
    """Return adopter-configured exempt prefixes from <root>/espalier.toml.

    Schema (flat top-level — matches the existing HarnessConfig fields
    that `espalier.config.load_config` filters via its flat key set):

        plan_exempt_prefixes = ["src/", "lib/"]

    Validation: each entry must be a non-empty string ending with "/",
    not absolute (no leading "/"), and contain no ".." path component.
    On ANY parse error or invalid entry, returns the empty tuple and writes a
    one-line advisory to stderr (strict mode, no adopter exemptions). When no
    TOML parser is importable (Py<3.11 without tomli), a regex fallback
    (`_regex_extract_exempt_prefixes`) recovers the flat list so the config is
    honored rather than silently dropped. Never raises.

    tools/cc/ has a zero-espalier-imports contract so this duplicates the
    schema parser. HarnessConfig.plan_exempt_prefixes is the espalier-side
    mirror; this helper is the hook-side reader.
    """
    config_path = root / "espalier.toml"
    if not config_path.exists():
        return ()
    if _tomllib is None:
        # No TOML parser (Py<3.11 hook interpreter without tomli): recover the
        # flat quoted-string list with a regex so the adopter's exempt config
        # still works instead of being silently dropped on every write. Falls
        # through to the SAME validator below as the parsed path.
        raw = _regex_extract_exempt_prefixes(config_path)
        if raw is None:
            return ()
    else:
        try:
            with open(config_path, "rb") as fh:
                data = _tomllib.load(fh)
        except (OSError, _tomllib.TOMLDecodeError) as exc:
            print(
                f"[plan_guard] malformed espalier.toml ({os_error_text(exc)}); "
                f"falling back to strict mode",
                file=sys.stderr,
            )
            return ()
        raw = data.get("plan_exempt_prefixes")
        if raw is None:
            plan_guard_table = data.get("plan_guard")
            bare_exempt = data.get("exempt_prefixes")
            if isinstance(plan_guard_table, dict) or bare_exempt is not None:
                print(
                    "[plan_guard] espalier.toml present but `plan_exempt_prefixes` "
                    "is missing at the TOML top level; the hook reads ONLY the "
                    "top-level flat key (not `[plan_guard]` table or bare "
                    "`exempt_prefixes`). Example: "
                    "plan_exempt_prefixes = [\"src/\"]. See CLAUDE.md "
                    "\"Plan Guard\" section.",
                    file=sys.stderr,
                )
            return ()
    if not isinstance(raw, list):
        print(
            f"[plan_guard] espalier.toml plan_exempt_prefixes must be a list "
            f"of strings; got {type(raw).__name__}; falling back to strict mode",
            file=sys.stderr,
        )
        return ()
    for entry in raw:
        if not isinstance(entry, str) or not entry:
            print(
                f"[plan_guard] invalid plan_exempt_prefixes entry {entry!r} "
                f"(must be non-empty string); falling back to strict mode",
                file=sys.stderr,
            )
            return ()
        if entry.startswith("/"):
            print(
                f"[plan_guard] invalid plan_exempt_prefixes entry {entry!r} "
                f"(absolute paths not allowed); falling back to strict mode",
                file=sys.stderr,
            )
            return ()
        if ".." in entry.split("/"):
            print(
                f"[plan_guard] invalid plan_exempt_prefixes entry {entry!r} "
                f"(contains '..' traversal); falling back to strict mode",
                file=sys.stderr,
            )
            return ()
        if not entry.endswith("/"):
            print(
                f"[plan_guard] invalid plan_exempt_prefixes entry {entry!r} "
                f"(must end with '/'); falling back to strict mode",
                file=sys.stderr,
            )
            return ()
    return tuple(raw)


_resolve_project_root = _hook_utils.resolve_project_root


def deny(reason: str) -> int:
    """Print deny JSON and return exit 0.

    Per Claude Code hook protocol: JSON on stdout is only processed on exit 0.
    Exit 2 would be ignored. See docs/SHARP_EDGES.md "Hook Exit Codes — Channel XOR".
    """
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(output))
    # truthy-zero so a `if rc: return rc` dispatch short-circuits after a deny
    # (no second decision JSON), exit code stays 0 (channel-XOR).
    return _hook_utils.DENIED


def _record_maintenance_bypass() -> None:
    """One advisory audit record per session when MAINTENANCE_MODE switches the
    plan requirement off (DEF-789; write_guard and stop_gate write the sibling
    records for theirs). Nothing was blocked, so it is in neither tier of
    ``/status --log`` and is counted on its own line. Record first, then the
    shared per-hook guard ``_integrity`` owns and session_start clears. Every
    step, the root resolution included, sits under one best-effort net: this
    runs on the allow path, and ``main``'s crash handler would otherwise turn
    a reporter's error into a deny."""
    try:
        root = _resolve_project_root()
        if _integrity.maintenance_bypass_recorded(root, "plan_guard"):
            return
        _integrity.append_audit(
            root,
            {"event_type": "pretooluse_bypassed_maintenance_mode",
             "details": {"hook": "plan_guard", "check": "plan-required"}},
            quiet=True,
        )
        _integrity.mark_maintenance_bypass_recorded(root, "plan_guard")
    except Exception:  # noqa: BLE001, S110 -- audit best-effort; hook protocol forbids stderr noise
        pass


def _audit_deny(root: Path, event_type: str, reason: str, **details: object) -> int:
    """Best-effort ``append_audit`` then ``deny`` — routes every no-active-plan
    block into the ``~/.espalier/audit`` log (metadata only: the channel + the
    repo-relative path, never file contents). Visibility layer, not a security
    boundary — a write failure must never make the hook raise, and the hook
    protocol forbids stderr noise on a deny path. Sister of
    ``write_guard._audit_deny``; hooks cannot share this via ``_hook_utils``
    (it is imported BY ``_integrity``, so a shared owner there would cycle)."""
    try:
        # ``quiet``: the writer's own OSError branch would otherwise warn on
        # stderr, beside the deny JSON on stdout.
        _integrity.append_audit(root, {"event_type": event_type, "details": details}, quiet=True)
    except Exception:  # noqa: BLE001, S110 -- audit best-effort; hook protocol forbids stderr noise
        pass
    return deny(reason)


# Aliased to `_hook_utils.normalize_path` (single source of truth). A non-str
# payload returns "<invalid>" instead of raising AttributeError — the same
# fail-closed shape `write_guard` uses via its own
# `_normalize_path = _hook_utils.normalize_path` alias.
_normalize_path = _hook_utils.normalize_path


def _is_exempt(rel_path: str, root: Path) -> bool:
    """Return True if path is exempt from plan requirement.

    Precedence chain:
      1. Universal prefixes — tests/, tools/cc/, .claude/, cc/, reports/
         (from EXEMPT_PREFIXES via _hook_utils.harness_exempt_prefixes).
      2. Self-host carve-out — espalier/ when the hook detects self-host
         context (also via _hook_utils.harness_exempt_prefixes).
      3. Adopter-configured prefixes — espalier.toml's flat top-level
         `plan_exempt_prefixes = [...]` (via _load_adopter_exempt_prefixes).
    All three sets share the NFKC+casefold normalization.

    Resolves the prefix list per-call via _hook_utils.harness_exempt_prefixes
    so the self-host overlay (espalier/ as exempt source) doesn't leak into
    user-repo behavior.

    Case-insensitive prefix match. See write_guard._is_protected for the same
    fix shape.

    Paths outside repo root never normalize to a relative form; _normalize_path
    returns the raw absolute string when relative_to(root) fails. Such paths are
    outside the harness's governance scope -- exempt them so plan-mode writes to
    ~/.claude/plans/* and similar do not trigger plan-required denials.
    write_guard handles symlink-into-protected-zone bypasses via its
    own _normalize_path that resolves symlinks before the protected
    check, so this exemption does not enable redirect attacks.
    """
    if Path(rel_path).is_absolute():
        return True
    # NFKC + casefold parity with write_guard._is_protected. See write_guard
    # docstring for the bypass class this closes.
    rel_norm = unicodedata.normalize("NFKC", rel_path).casefold()
    for prefix in _hook_utils.harness_exempt_prefixes(root):
        if rel_norm.startswith(unicodedata.normalize("NFKC", prefix).casefold()):
            return True
    # Adopter-configured prefixes loaded out of espalier.toml. Same
    # normalization so a user adding "Src/" matches "src/MyApp/foo.py".
    adopter_prefixes = _load_adopter_exempt_prefixes(root)
    for prefix in adopter_prefixes:
        if rel_norm.startswith(unicodedata.normalize("NFKC", prefix).casefold()):
            return True
    p = Path(rel_path)
    if p.parent == Path("."):  # Root-level file
        name = p.name
        if name in PLAN_REQUIRED_ROOT_FILES:
            return False
        ext = p.suffix.lower()
        if ext in PLAN_REQUIRED_ROOT_EXTENSIONS:
            # Flat-layout escape hatch: adopters whose source lives at the repo
            # root opt out with `plan_exempt_prefixes = ["./"]`. The sentinel
            # can't match via startswith above (no bare root filename starts
            # with "./"), so honor it explicitly here.
            if _ROOT_SOURCE_SENTINEL in adopter_prefixes:
                return True
            return False
        # Other root-level files (e.g. ESPALIER_MEMORY.md, scratch notes) are exempt
        return True
    # All other non-root non-prefix paths require a plan
    return False


def _is_root_source_file(rel_path: str) -> bool:
    """True when rel_path is a plan-required source file at the repo root — the
    case the `./` sentinel exempts. Used only to pick the targeted deny hint;
    by the time a root source file reaches the deny path it is definitionally
    un-exempted (the sentinel isn't configured), so this needs no re-check of
    the prefix list."""
    p = Path(rel_path)
    if p.is_absolute() or p.parent != Path("."):
        return False
    if p.name in PLAN_REQUIRED_ROOT_FILES:
        return False
    return p.suffix.lower() in PLAN_REQUIRED_ROOT_EXTENSIONS


def _plan_state_label(root: Path) -> str:
    """Return a short label describing the plan's state, for deny messages.

    Returns one of:
      "status=<value>"    — file exists and parses; <value> is the literal status
                            (typically "complete", "planned", "cancelled", "in_progress",
                            "" for empty, or any other recorded string)
      "no-steps"          — file parses but `steps` is empty or missing
      "missing"           — execution_plan.json does not exist
      "malformed"         — file exists but is not valid JSON or not an object
    """
    plan_path = root / "cc" / "execution_plan.json"
    # Read with a symlink-REFUSING fd-level open. A forged symlink at
    # cc/execution_plan.json pointing at attacker JSON (status=in_progress)
    # would otherwise be FOLLOWED here and OPEN the PreToolUse mutation gate.
    # read_text_nofollow raises FileNotFoundError when absent and OSError on a
    # symlink / non-regular / oversize target, so a planted symlink falls into
    # "malformed" -> _has_active_plan False -> gate stays CLOSED (fail-closed).
    try:
        # within=root also refuses a symlinked cc/ ANCESTOR: O_NOFOLLOW alone
        # guards only the final component, so a symlinked governed parent dir
        # would otherwise be followed and reopen the gate.
        raw = _hook_utils.read_text_nofollow(plan_path, within=root)
    except FileNotFoundError:
        return "missing"
    except (OSError, UnicodeDecodeError):
        # read_text_nofollow decodes UTF-8, so a non-UTF-8 plan file raises
        # UnicodeDecodeError — treat it as malformed (fail-closed), matching
        # the _hook_utils.has_active_plan canon the predicate now delegates to.
        return "malformed"
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return "malformed"
    if not isinstance(data, dict):
        return "malformed"
    if not data.get("steps"):
        return "no-steps"
    return f"status={data.get('status', '')!r}"


def _has_active_plan(root: Path) -> bool:
    """Return True when cc/execution_plan.json shows an OPEN mutation window.

    Open means status == "in_progress" AND the plan file is a JSON object
    with at least one step. Any other state (complete, planned, cancelled,
    missing file, malformed JSON, empty status, unknown status, empty steps)
    returns False so the caller denies the write.

    Accepting "complete" here as well would keep the mutation window open after
    a task finished, weakening "writes require an active plan" to "writes
    require any recent plan".

    Delegates the predicate to the single owner _hook_utils.has_active_plan
    (which unions this hook's symlink-refusing read with task_router's full
    error domain); the _plan_state_label helper above stays for the descriptive
    deny message.
    """
    return _hook_utils.has_active_plan(root)


def _check_path(file_path: str, root: Path) -> int:
    """Deny (exit 0 + structured JSON via ``deny``) if path requires a plan
    and none is active; else allow (exit 0).

    The channel-XOR contract (see ``docs/external/cc-hook-protocol.md``)
    means PreToolUse hooks always exit 0; the block channel is the JSON
    payload on stdout, not exit code 2.
    """
    if not file_path:
        return 0
    return _check_rel(_normalize_path(file_path, root), root)


def _check_rel(rel_path: str, root: Path) -> int:
    """Plan-required decision on an already-normalised repo-relative path.

    Split from ``_check_path`` so the MCP leaf-walk can feed leaves normalised
    by the FS-free ``normalize_path_str`` through the SAME exempt / active-plan
    decision without re-running ``_normalize_path`` (resolve) per leaf.
    """
    if not rel_path:
        return 0
    if _is_exempt(rel_path, root):
        return 0
    if _has_active_plan(root):
        return 0
    state = _plan_state_label(root)
    # A root-level source file can't be covered by a directory prefix, so give
    # it the "./" sentinel hint instead of the generic src/ one.
    hint = _ROOT_SOURCE_HINT if _is_root_source_file(rel_path) else _PLAN_EXEMPT_HINT
    return _audit_deny(
        root, "pretooluse_blocked_no_active_plan",
        _denial_reasons.NO_ACTIVE_PLAN_FILE.format(
            state=state, path=rel_path, exempt_hint=hint,
        ),
        tool="write_edit", path=rel_path,
    )


def main() -> int:
    """Public entry-point. Umbrella try/except catches any uncaught
    exception in _run_main and converts it to a deny() — the Claude
    Code hook protocol treats exit 1 as a non-blocking script error,
    so we MUST fail-closed inside the hook process itself.

    Sister-pattern of write_guard.main.
    """
    try:
        return _run_main()
    except BaseException as exc:  # noqa: BLE001 — fail-closed crash guard
        # check_exception_policy.py exempts BaseException at hook entrypoints;
        # this noqa is documentary.
        error_type = type(exc).__name__
        print(
            f"[ERROR] plan_guard crashed: {error_type}: {os_error_text(exc)}",
            file=sys.stderr,
        )
        # Through the audited funnel (DEF-803, the class): a wedged guard
        # denies every source write, and the day it did was invisible in
        # ``/status --log``. The root is resolved best-effort here -- the
        # crash may have been in resolving it -- and the record carries the
        # exception's class, never its message (a message can quote a path
        # or a file's contents). Sister of write_guard.main.
        #
        # INVARIANT: nothing between this ``except`` and the emit may prevent
        # the emit. The root fallback and the record write both swallow what
        # they can; a KeyboardInterrupt inside them is the one thing that
        # escapes, and the hook then exits non-zero, which the protocol reads
        # as allow -- which is also why an interrupt inside ``_run_main`` is
        # denied here rather than re-raised (a propagated interrupt is an
        # allow for a PreToolUse guard). Add nothing here that can raise past
        # those handlers.
        try:
            root = _resolve_project_root()
        except BaseException:  # noqa: BLE001 — best-effort; never mask the deny
            root = Path(".")
        return _audit_deny(
            root, "pretooluse_blocked_internal_error",
            _denial_reasons.PLAN_GUARD_INTERNAL_ERROR,
            hook="plan_guard", error=error_type,
        )


def _run_main() -> int:
    if _maintenance_mode.is_active("plan_guard", action="plan-required check bypassed"):
        _record_maintenance_bypass()
        return 0
    data = _hook_utils.read_stdin_safely()

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    # Pass read-only tools immediately
    if tool_name not in MUTATION_TOOLS and not tool_name.startswith("mcp__"):
        return 0

    root = _resolve_project_root()

    # Bash / PowerShell: write-intent check MUST run before read-only allowlist.
    # Commands like `echo x > src/x.py` look read-only by first token but are not.
    # Dead under current matcher; see header banner.
    if tool_name in ("Bash", "PowerShell"):
        command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
        if bash_has_write_intent(command):
            if _has_active_plan(root):
                return 0
            state = _plan_state_label(root)
            return _audit_deny(
                root, "pretooluse_blocked_no_active_plan",
                _denial_reasons.NO_ACTIVE_PLAN_BASH.format(
                    state=state, exempt_hint=_PLAN_EXEMPT_HINT,
                ),
                tool="bash", path="<bash write-intent>",
            )
        if READONLY_BASH_PATTERN.match(command):
            return 0
        return 0  # Unknown command pattern — pass through (best effort)

    # MCP tools: distinguish write-intent tool names from pure reads. Denying
    # every mcp__ call without an active plan would block `mcp__filesystem__
    # read_file`, which is just a read with no write side-effects, breaking
    # normal MCP usage on any session without an active execution plan.
    # Discrimination is by tool-name keyword (same shape as bash write-intent
    # detection). Conservatively false-allow on ambiguous names; the
    # write_guard layer is the second line of defense for protected zones.
    # Dead under current matcher; see header banner.
    if tool_name.startswith("mcp__"):
        if not _mcp_tool_is_write(tool_name):
            return 0
        # Leaf-walk the payload (shared with write_guard via
        # _hook_utils.iter_mcp_path_leaves) so a plan-gated write nested in
        # ``{files:[{path}]}`` / ``{batch:{files:[{path}]}}`` can't bypass the
        # plan check. Act on the SAME MCP_PATH_FIELDS the field set enumerates —
        # plan_guard's predicate (deny ANY non-exempt path) would over-fire on
        # prose if it were key-agnostic like write_guard, so it gates on
        # path-shaped governing keys ONLY (a missed write via a novel key is
        # recoverable plan-discipline friction, not a security fail-open).
        # Leaves normalised FS-free (normalize_path_str).
        if isinstance(tool_input, dict):
            try:
                for key, _location, leaf in _hook_utils.iter_mcp_path_leaves(tool_input):
                    if key not in _hook_utils.MCP_PATH_FIELDS:
                        continue
                    rc = _check_rel(_hook_utils.normalize_path_str(leaf, root), root)
                    if rc:
                        return rc
            except _hook_utils.MCPPayloadUnverifiable:
                # Too deep/wide to verify which paths it writes -> fail closed:
                # require a plan unless one is already active.
                if _has_active_plan(root):
                    return 0
                return _audit_deny(
                    root, "pretooluse_blocked_no_active_plan",
                    _denial_reasons.NO_ACTIVE_PLAN_FILE.format(
                        state=_plan_state_label(root),
                        path="<unverifiable MCP payload>",
                        exempt_hint=_PLAN_EXEMPT_HINT,
                    ),
                    tool="mcp", path="<unverifiable MCP payload>",
                )
        return 0

    # Write / Edit use `file_path`; NotebookEdit uses `notebook_path` (confirmed
    # against the Claude Code Agent SDK reference, not the code under test). Read
    # both, file_path first, so a NotebookEdit source `.ipynb` edit is still
    # plan-gated -- a file_path-only read would skip every NotebookEdit.
    # The write_guard twin is check_write_edit.
    if isinstance(tool_input, dict):
        file_path = tool_input.get("file_path")
        if file_path is None:
            file_path = tool_input.get("notebook_path")
        file_path = file_path or ""
    else:
        file_path = ""
    return _check_path(file_path, root)


if __name__ == "__main__":
    raise SystemExit(int(main()))  # coerce the truthy-zero sentinel to a plain 0
