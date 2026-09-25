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
import os
import sys
from dataclasses import dataclass
from pathlib import Path

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
    boolean pin exists to prevent. ``test_explain_path.py`` pins these labels."""
    if Path(rel).is_absolute():
        return "exempt -- outside repo (absolute path)"
    folded = _hook_utils_normcase(rel)
    for prefix in _hook_utils.harness_exempt_prefixes(root):
        if folded.startswith(_hook_utils_normcase(prefix)):
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
        if p.suffix.lower() in plan_guard.PLAN_REQUIRED_ROOT_EXTENSIONS:
            if plan_guard._ROOT_SOURCE_SENTINEL in adopter_prefixes:
                return "exempt -- root-level source opted out via espalier.toml `plan_exempt_prefixes = [\"./\"]`"
            return "plan required -- root-level source (opt out with `plan_exempt_prefixes = [\"./\"]`)"
        return "exempt -- root-level non-listed non-source file"
    return "plan required -- non-exempt path"


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
    write_denied = protected and not allowed
    write_zone = _write_zone_label(rel, root) if protected else ""

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
    )


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
    the live bypasses that actually decide the outcome this session."""
    parts: list[str] = []
    if write_denied:
        parts.append(f"writes DENIED ({write_zone})")
    elif protected and allowed:
        parts.append(f"writes allowed (allowlisted within {write_zone})")
    else:
        parts.append("writes allowed (unprotected)")
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
    base = "; ".join(parts)
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
        f"\n"
        f"  => {exp.verdict}"
    )


if __name__ == "__main__":  # CLI shim: `python _explain_path.py <path> [repo_root]`.
    # The /status --explain submode imports explain()/render() directly; this
    # block is convenience for direct invocation + manual smoke. Prints live
    # under the __main__ guard so they read as CLI output, not a hook-event
    # handler's stdout — mirrors _recall.py (review_agent_audit exempts guarded
    # prints from the block-JSON-corruption rule).
    _args = sys.argv[1:]
    if not _args:
        print("usage: _explain_path.py <repo-relative-path> [repo_root]", file=sys.stderr)
        raise SystemExit(2)
    _root = Path(_args[1]).resolve() if len(_args) > 1 else Path.cwd()
    print(render(explain(_args[0], _root)))
    raise SystemExit(0)
