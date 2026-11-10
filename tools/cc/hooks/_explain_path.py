#!/usr/bin/env python3
"""Read-only per-path enforcement read-out for ``/status --explain <path>``.

Given a repo-relative path, report what the path-conditioned hooks WOULD do and
why — is it plan-gated, in a write_guard protected zone, allowlisted, exempt, and
by which rule. It pairs with the audit log (``/status --log``, what the hooks
*did*): ``--explain`` shows what they *will* do on a given path.

The load-bearing constraint: a read-out that computed protection/exemption
DIFFERENTLY from what the hooks enforce would lie with authority. So every static
verdict here is derived from the hooks' OWN predicates — imported, never copied:

  * write_guard protection -> ``_protected_zones._is_protected`` / ``_is_allowed``
  * plan exemption          -> ``plan_guard._is_exempt``
  * path normalization      -> ``_hook_utils.normalize_path`` (what the hooks use)

Live session state (maintenance mode, whether a plan is currently active) is
REPORTED as a separate note — never folded into the static path pin — because it
reflects the session, not the path. ``tests/test_explain_path.py`` pins the
resolver to the predicates (delegation + value cross-check + no-copied-constants).

Scope of the static verdict: it reports the PATH-conditioned decision. A handful
of runtime factors the hooks also weigh are deliberately NOT in the static pin —
maintenance-mode bypass and active-plan state (reported as live notes), plus a
live kill-switch (denies every call), dangerous-command Bash patterns, MCP
write-intent, and write_guard's hardlink-inode backstop. So ``write_denied`` can
UNDER-report (a hardlink alias of a protected file at an unprotected path reads
"unprotected") — the static read-out never claims to model those runtime paths.

It is Espalier's hooks' verdict, never the session's (DEF-1113): a PreToolUse
hook wired beside Espalier's, or a ``permissions.deny`` Edit/Write rule, can
deny a write this read-out calls allowed. The net line says whose verdict it is,
and the ``unmodelled`` line names what the project's two settings files hold
that it does not model -- each other PreToolUse hook whose matcher can reach a
file write, and a count of the Edit/Write deny rules, whose globs are never
re-matched here -- and says that user-level, plugin and managed hooks are not
listed.

Stdlib-only, zero-espalier, sibling imports only — same pattern as the hooks.

Note: this module deliberately does NOT ``from __future__ import annotations``.
Under Python 3.14, a ``@dataclass`` with stringized annotations makes
``dataclasses._is_type`` look up ``sys.modules[cls.__module__]``. The canonical
fix is registering the module in ``sys.modules`` before ``exec_module`` (the
importlib idiom; ``tests/test_explain_path.py::_load_modules`` does this, and a
normal ``import`` does it automatically). Omitting the future-import is the
belt-and-suspenders half: real (non-string) field annotations sidestep the
lookup entirely, so a ``@dataclass`` here loads cleanly even under a spec-load
that forgets to pre-register — robust to any loader, at the cost of the
future-annotations convention the sibling hooks follow.
"""
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# A kept, older sibling is named with its repair, never a traceback that names
# an attribute: an uncaught exception loads hooks/_start_refusal.py by path and
# hands it to that module's refuse_kept_siblings. The one text of this block,
# and why each line is there, is tests/test_kept_sibling.py's ARM_BLOCK.
if __name__ == "__main__":
    from types import TracebackType as _KeptTraceback

    _KEPT_FROM = Path(__file__).resolve().parent
    _KEPT_SCRIPT = Path(__file__).name
    _KEPT_BEFORE = sys.excepthook

    def _name_a_kept_sibling(kind: type[BaseException], exc: BaseException, tb: _KeptTraceback | None) -> None:
        sys.excepthook = _KEPT_BEFORE
        try:
            import importlib.util
            at = (_KEPT_FROM if _KEPT_FROM.name == "hooks" else _KEPT_FROM / "hooks") / "_start_refusal.py"
            spec = importlib.util.spec_from_file_location("_start_refusal_by_path", at)
            if spec is not None and spec.loader is not None:
                reader = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = reader
                spec.loader.exec_module(reader)
                refuse = getattr(reader, "refuse_kept_siblings", None)
                if callable(refuse):
                    reconfigure = getattr(sys.stderr, "reconfigure", None)
                    if callable(reconfigure):
                        reconfigure(encoding="utf-8", errors="replace")
                    refuse(_KEPT_SCRIPT)
        # fail-open: ok deliberate without the reader a kept sibling keeps its traceback, as before
        except Exception:  # noqa: BLE001, S110
            pass
        sys.excepthook(kind, exc, tb)

    sys.excepthook = _name_a_kept_sibling

# Co-located hook siblings — same zero-espalier-import shim every hook uses.
sys.path.insert(0, str(Path(__file__).parent))
import _hook_utils  # noqa: E402
import _maintenance_mode  # noqa: E402
import _protected_zones  # noqa: E402
import plan_guard  # noqa: E402


@dataclass(frozen=True)
class PathExplanation:
    """A per-path enforcement read-out. Static verdicts (``protected`` ..
    ``plan_required``) are pinned to the hook predicates; ``maintenance_active``
    and ``plan_active`` are live session state."""

    rel: str
    # write_guard (static, pinned to _protected_zones)
    protected: bool
    allowed: bool
    write_denied: bool
    write_zone: str
    # plan_guard (static, pinned to plan_guard._is_exempt)
    plan_exempt: bool
    plan_required: bool
    plan_rule: str
    # live session state (reported, not pinned)
    maintenance_active: bool
    plan_active: bool
    # net one-line synthesis
    verdict: str
    # what the project settings hold that the verdict does not model (DEF-1113)
    unmodelled: str = ""


def _write_zone_label(rel: str, root: Path) -> str:
    """Human label for the matched protected zone/file (cosmetic — the verdict
    itself comes from ``_is_protected``). Reads the SoT sets, never copies them.
    Uses ``_protected_zones._fs_equiv`` — the SAME canonicaliser ``_is_protected``
    uses — so the label recognises the exotic (trailing-dot / NTFS-ADS) spellings
    the predicate does, instead of falling to the generic label on a mismatch."""
    folded = _protected_zones._fs_equiv(rel, all_components=True)
    for protected_file in _protected_zones.PROTECTED_FILES:
        if folded == _protected_zones._fs_equiv(protected_file, all_components=True):
            return f"exact protected file `{protected_file}`"
    for prefix in _hook_utils.harness_protected_prefixes(root):
        pfx = _protected_zones._fs_equiv(prefix, all_components=True)
        if folded == pfx.rstrip("/") or folded.startswith(pfx):
            return f"zone `{prefix}`"
    zone = _hook_utils.adopter_zone_for(rel, root)
    if zone is not None:
        prefix, kind = zone
        key = {k: kk for kk, k in _hook_utils.ADOPTER_ZONE_KEYS}[kind]
        return f"espalier.toml `{key}` entry `{prefix}`"
    return "protected zone"


def _plan_rule_label(rel: str, root: Path) -> str:
    """Name the rule that decided the plan verdict, MIRRORING
    ``plan_guard._is_exempt``'s precedence branch-for-branch and reading
    plan_guard's own constant SoT (``PLAN_REQUIRED_ROOT_FILES`` /
    ``PLAN_REQUIRED_ROOT_EXTENSIONS`` / ``_ROOT_SOURCE_SENTINEL``), never a
    private copy. The boolean verdict is already pinned to ``_is_exempt``; this
    names WHY, and must not drift from it — a wrong reason (e.g. offering a
    `./`-sentinel opt-out for a file that ``PLAN_REQUIRED_ROOT_FILES``
    short-circuits) is the same "read-out lies with authority" failure the
    boolean pin exists to prevent. ``test_explain_path.py`` pins these labels.
    Rooted is `_hook_utils.rooted`, the exemption's own judge (DEF-1175)."""
    if _hook_utils.rooted(rel):
        return "exempt -- outside repo (absolute path)"
    folded = _hook_utils_normcase(rel)
    # The stack's own test roots, read from the producer rather
    # than re-deriving its branch: a hit on one is labelled as such, since the
    # remedy for a wrong one differs from a universal prefix's.
    stack_roots = set(_hook_utils.stack_test_roots(root))
    for prefix in _hook_utils.harness_exempt_prefixes(root):
        if folded.startswith(_hook_utils_normcase(prefix)):
            if prefix in stack_roots:
                return f"exempt -- your stack's test root `{prefix}`"
            return f"exempt -- harness-universal prefix `{prefix}`"
    adopter_prefixes = plan_guard._load_adopter_exempt_prefixes(root)
    for prefix in adopter_prefixes:
        if prefix != plan_guard._ROOT_SOURCE_SENTINEL and folded.startswith(
            _hook_utils_normcase(prefix)
        ):
            return f"exempt -- espalier.toml `plan_exempt_prefixes` entry `{prefix}`"
    p = Path(rel)
    if p.parent == Path("."):  # root-level file — mirror _is_exempt's root branch
        if p.name in plan_guard.PLAN_REQUIRED_ROOT_FILES:
            return "plan required -- listed root doc/config (not exemptible via `plan_exempt_prefixes`)"
        if p.suffix.lower() in plan_guard._plan_required_root_extensions(root, p.suffix.lower()):
            if plan_guard._ROOT_SOURCE_SENTINEL in adopter_prefixes:
                return "exempt -- root-level source opted out via espalier.toml `plan_exempt_prefixes = [\"./\"]`"
            return (
                "plan required -- root-level source (opt out with `plan_exempt_prefixes = [\"./\"]`)"
                + _config_fault_tail(root)
            )
        return "exempt -- root-level non-listed non-source file"
    return "plan required -- non-exempt path" + _config_fault_tail(root)


def _config_fault_tail(root: Path) -> str:
    """Why the hook honoured none of the adopter's ``plan_exempt_prefixes``
    (DEF-1022), as a clause on the plan-rule label -- only a fault: a valid
    list is the adopter's own statement, and the label stays the rule, the
    same on every tree (the storyboard and README read-outs quote it)."""
    fault = plan_guard._config_fault_note(root)
    return f"; {fault.rstrip('.')}." if fault else ""


def _hook_utils_normcase(value: str) -> str:
    """NFKC+casefold fold, matching ``plan_guard._is_exempt``'s comparison."""
    import unicodedata

    return unicodedata.normalize("NFKC", value).casefold()


def explain(path: str, root: Path) -> PathExplanation:
    """Classify ``path`` (relative to the checkout containing it -- the root, or a
    registered worktree of it) against the live enforcement predicates."""
    rel = _hook_utils.normalize_path(path, root)

    protected = _protected_zones._is_protected(rel, root)
    allowed = _protected_zones._is_allowed(rel)
    # The adopter's generated_paths is path-conditioned and refused on the
    # Write / Edit / NotebookEdit channel (write_guard.check_write_edit), so
    # the static read-out models it; a hand edit there IS denied.
    adopter_zone = _hook_utils.adopter_zone_for(rel, root)
    generated = adopter_zone is not None and adopter_zone[1] == "generated"
    write_denied = (protected and not allowed) or generated
    write_zone = _write_zone_label(rel, root) if (protected or generated) else ""

    plan_exempt = plan_guard._is_exempt(rel, root)
    plan_required = not plan_exempt
    plan_rule = _plan_rule_label(rel, root)

    maintenance_active = _maintenance_mode._maintenance_mode_active(
        os.environ.get(_maintenance_mode.ENV_VAR)
    )
    plan_active = plan_guard._has_active_plan(root)

    verdict = _net_verdict(
        write_denied=write_denied,
        allowed=allowed,
        protected=protected,
        write_zone=write_zone,
        plan_required=plan_required,
        plan_active=plan_active,
        maintenance_active=maintenance_active,
    )

    return PathExplanation(
        rel=rel,
        protected=protected,
        allowed=allowed,
        write_denied=write_denied,
        write_zone=write_zone,
        plan_exempt=plan_exempt,
        plan_required=plan_required,
        plan_rule=plan_rule,
        maintenance_active=maintenance_active,
        plan_active=plan_active,
        verdict=verdict,
        unmodelled=_unmodelled_line(root),
    )


# The file-writing tools a PreToolUse matcher can name, and the permission-rule
# tool names that cover a file write (Claude Code's Edit rules apply to every
# built-in file-editing tool; a Write rule is accepted beside them).
_WRITE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
_SETTINGS_FILES = (".claude/settings.json", ".claude/settings.local.json")
_HOOKS_SHOWN = 3
_COMMAND_SHOWN = 80
# A matcher holding any of these is a pattern, not a plain list of names.
_REGEX_SYNTAX = re.compile(r"[.*+?\[\](){}^$\\]")


def _matcher_reaches_a_write(matcher: object) -> bool:
    """Can this PreToolUse matcher fire on a file write? No matcher, ``""`` and
    ``*`` match every tool; a plain ``|`` list of tool names counts when it
    names a write tool; any other shape (a regex, ``mcp__.*``) counts without
    being evaluated, since a pattern from a settings file is never compiled in
    a hook (the dot-star gate cannot prove one safe): naming a hook that cannot
    deny is the cheaper mistake than hiding one that can."""
    if matcher is None or matcher == "" or matcher == "*" or not isinstance(matcher, str):
        return True
    if _REGEX_SYNTAX.search(matcher):
        return True
    return any(name.strip() in _WRITE_TOOLS for name in matcher.split("|"))


def _entry_text(entry: dict) -> str:
    """A hook entry as the line it runs: the inline ``command``, or the
    exec form's ``command`` and its ``args`` joined (``session_start._entry_argv``
    reads the same two forms). A hook of another type (an ``http`` hook, a
    ``prompt`` hook) runs no command and can deny all the same, so it is named
    by its type and, for ``http``, its URL."""
    kind = entry.get("type")
    if isinstance(kind, str) and kind and kind != "command":
        url = entry.get("url")
        return f"{kind} hook" + (f" {url.strip()}" if isinstance(url, str) and url.strip() else "")
    command = entry.get("command")
    args = entry.get("args")
    words = [command] if isinstance(command, str) else []
    if isinstance(args, list):
        words += [a for a in args if isinstance(a, str)]
    return " ".join(w.strip() for w in words if w.strip())


def _settings_findings(root: Path, rel: str) -> "tuple[list[str], int, str]":
    """``(other write hooks, Edit/Write deny rule count, why unread)`` for one
    settings file; an absent file is ``([], 0, "")``."""
    path = root / rel
    if not path.is_file():
        return [], 0, ""
    try:
        data = json.loads(path.read_bytes().decode("utf-8-sig"))
    except (OSError, ValueError) as exc:  # fail-open: ok deliberate -- an unreadable settings file is named on the line, never raised
        return [], 0, type(exc).__name__
    if not isinstance(data, dict):
        return [], 0, "not a JSON object"
    hooks: list[str] = []
    groups = data.get("hooks", {}).get("PreToolUse") if isinstance(data.get("hooks"), dict) else None
    for group in groups if isinstance(groups, list) else []:
        if not isinstance(group, dict) or not _matcher_reaches_a_write(group.get("matcher")):
            continue
        entries = group.get("hooks")
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            text = _entry_text(entry)
            # Espalier's own guards are what the verdict above already models.
            if not text or "tools/cc/hooks/" in text.replace("\\", "/"):
                continue
            if len(text) > _COMMAND_SHOWN:
                text = text[: _COMMAND_SHOWN - 3] + "..."
            matcher = group.get("matcher")
            hooks.append(f"`{text}` ({rel}" + (f", matcher `{matcher}`)" if matcher else ")"))
    perms = data.get("permissions")
    deny = perms.get("deny") if isinstance(perms, dict) else None
    denies = sum(
        1 for rule in (deny if isinstance(deny, list) else [])
        if isinstance(rule, str) and rule.strip().split("(", 1)[0].strip() in _WRITE_TOOLS
    )
    return hooks, denies, ""


def _unmodelled_line(root: Path) -> str:
    """What the project's settings files hold that can deny a write the
    verdict does not model, as one line (DEF-1113)."""
    hooks: list[str] = []
    denies = 0
    unread: list[str] = []
    for rel in _SETTINGS_FILES:
        found, count, why = _settings_findings(root, rel)
        hooks += found
        denies += count
        if why:
            unread.append(f"{rel} could not be read ({why})")
    parts: list[str] = []
    if hooks:
        shown = "; ".join(hooks[:_HOOKS_SHOWN])
        more = len(hooks) - _HOOKS_SHOWN
        noun = "hook" if len(hooks) == 1 else "hooks"
        parts.append(f"{len(hooks)} other PreToolUse {noun} that can deny a write: {shown}"
                     + (f"; and {more} more" if more > 0 else ""))
    if denies:
        parts.append(f"{denies} permissions.deny Edit/Write rule{'' if denies == 1 else 's'} (globs not matched here)")
    parts += unread
    if not parts:
        parts.append("other PreToolUse hooks and permissions.deny Edit/Write rules: "
                     "none in .claude/settings.json or .claude/settings.local.json")
    parts.append("user-level, plugin and managed hooks are not listed")
    return "; ".join(parts)


def _net_verdict(
    *,
    write_denied: bool,
    allowed: bool,
    protected: bool,
    write_zone: str,
    plan_required: bool,
    plan_active: bool,
    maintenance_active: bool,
) -> str:
    """One-line plain-language synthesis of the two static verdicts, qualified by
    the live bypasses that actually decide the outcome this session. It opens by
    saying whose verdict it is: Espalier's hooks', which another PreToolUse hook
    or a permissions rule can overrule (DEF-1113; the ``unmodelled`` line)."""
    parts: list[str] = []
    if write_denied:
        parts.append(f"writes DENIED ({write_zone})")
    elif protected and allowed:
        parts.append(f"writes allowed (allowlisted within {write_zone})")
    else:
        # Outside Espalier's zones, never "unprotected": the unmodelled line
        # names what else can deny the write (DEF-1113).
        parts.append("writes allowed (outside their zones)")
    if plan_required:
        # State the POSITIVE case too. The read-out was already fail-safe in this
        # direction -- with a plan active it simply omitted the clause, so it
        # never claimed an edit would be blocked when it would not -- but silence
        # reads as "unknown" rather than "satisfied". Cosmetic legibility, not a
        # defect: do not promote this beyond a wording fix.
        parts.append(
            "edits require an active plan"
            + ("; one is active" if plan_active else "; none is active")
        )
    else:
        parts.append("no plan required")
    base = "Espalier's hooks: " + "; ".join(parts)
    if maintenance_active:
        # Scope the claim precisely: maintenance mode bypasses the protected-zone
        # and plan checks, but write_guard STILL denies on a live kill-switch and
        # on dangerous-command patterns (per the maintenance-mode table in the
        # root docs) — so "nothing is denied" would be a false reassurance in the
        # exact degraded state where the read-out most needs to be true.
        return (
            "MAINTENANCE MODE active -- protected-zone + plan checks are bypassed this "
            "session (kill-switch + dangerous-command denials still fire). "
            f"Without maintenance mode: {base}."
        )
    return base + "."


def render(exp: PathExplanation) -> str:
    """Render a ``PathExplanation`` as a readable multi-line block."""
    if exp.write_denied:
        write_line = f"DENIED -- protected {exp.write_zone}"
    elif exp.protected and exp.allowed:
        write_line = f"allowed -- allowlisted within {exp.write_zone}"
    else:
        write_line = "allowed -- unprotected"

    plan_line = ("exempt" if exp.plan_exempt else "REQUIRES an active plan") + f"  ({exp.plan_rule})"

    maint = (
        "ON -- protected-zone + plan checks bypassed this session"
        if exp.maintenance_active
        else "off"
    )
    plan_state = "active" if exp.plan_active else "none active"

    return (
        f"Path: {exp.rel}\n"
        f"\n"
        f"  plan_guard : {plan_line}\n"
        f"  write_guard: {write_line}\n"
        f"  live state : maintenance mode {maint}; plan {plan_state}\n"
        f"  unmodelled : {exp.unmodelled}\n"
        f"\n"
        f"  => {exp.verdict}"
    )


if __name__ == "__main__":  # CLI shim: `python _explain_path.py <path> [repo_root]`.
    # The /status --explain submode imports explain()/render() directly; this
    # block is convenience for direct invocation + manual smoke. Prints live
    # under the __main__ guard so they read as CLI output, not a hook-event
    # handler's stdout — mirrors _recall.py (review_agent_audit exempts guarded
    # prints from the block-JSON-corruption rule).
    # UTF-8 on both streams whatever the code page: the explained path is the
    # operator's and may be any text (the same inline pin _recall.py carries).
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    _args = sys.argv[1:]
    if not _args:
        # voice: cli the usage line of a command-line entry point, which exits 2
        print("usage: _explain_path.py <repo-relative-path> [repo_root]", file=sys.stderr)
        raise SystemExit(2)
    _root = Path(_args[1]).resolve() if len(_args) > 1 else Path.cwd()
    print(render(explain(_args[0], _root)))
    raise SystemExit(0)
