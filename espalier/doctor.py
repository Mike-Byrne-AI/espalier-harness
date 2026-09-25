"""Doctor — pre-flight health classifier for Espalier-Harness repos.

Status ladder (most to least severe):
- **fail** — required managed surface is missing or unreadable.
- **warn** — stale-but-present artifacts, or missing-from-saved-plan drift.
- **pass** — fresh successful `init` leaves the repo coherent here.

The required-file list is read from `surface_contract.get_required_init_files()`
so `init` and `doctor` can never disagree about what a fresh repo must contain.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

from espalier import surface_contract
from espalier._venv import (
    interpreter_site_token,
    interpreter_token,
    is_statusline_shim_head,
    resolves_only_inside,
    venv_root_of,
)
from espalier._integrity_bridge import load_integrity_module
from espalier._text import plural
from espalier._python_floor import floor_text, interpreter_meets_floor, is_python3_banner
from espalier._report_io import load_harness_plan, report_is_json_object
from espalier.audit_accuracy import extract_count_for_label
from espalier.diffing import diff_repo
from espalier.managed_markers import seed_is_untouched
from espalier.managed_paths import (
    HARNESS_OWNED_ROOTS,
    STANDARD_MANAGED_SETTINGS,
    STATUSLINE_SCRIPT,
    STATUSLINE_SHIM,
    fallback_managed_paths,
    managed_paths_from_plan,
    ownership_summary,
    self_host_managed_paths,
)
from espalier.proofs import run_cc_surface_gate
from espalier.recovery import assess_repo_state
from espalier.reflection import reflect_repo
from espalier.proofs import first_error_detail
from espalier.self_hosting import gate_failure_reason, run_self_host_check


# Files `init` always deploys beyond the contract's required-init list.
AUXILIARY_REQUIRED_PATHS: tuple[str, ...] = (
    ".claude/settings.json",
    "reports/repo_fingerprint.json",
    "reports/harness_config.json",
)


def _load_plan(repo_root: Path) -> dict[str, Any] | None:
    # Single owner. Full exception set (a non-UTF-8 / BOM-prefixed
    # harness_config.json raises UnicodeDecodeError, an exists()->read race
    # raises OSError): see espalier._report_io.load_harness_plan.
    return load_harness_plan(repo_root)


def _settings_reaches_a_read(settings_path: Path) -> bool:
    """True when reading ``settings.json`` would say something the caller
    must hear -- it is present, it is a dangling symlink (lexists True,
    exists False), or a parent denies traversal -- and False only for an
    honest absence, which ``init`` owns. By errno, never ``Path.exists()``:
    the pathlib call answered a locked parent per interpreter (DEF-763)."""
    presence, _detail = surface_contract.path_presence(settings_path)
    return presence != surface_contract.PRESENCE_ABSENT or os.path.islink(settings_path)


def _surface_presence(repo_root: Path) -> dict[str, Any]:
    required = tuple(surface_contract.get_required_init_files()) + AUXILIARY_REQUIRED_PATHS
    present = [
        p for p in required
        if surface_contract.path_presence(repo_root / p)[0] == surface_contract.PRESENCE_PRESENT
    ]
    complete = len(present) == len(required)
    return {
        "required": list(required),
        "surface_present": complete,
        "surface_missing": not complete,
        "present_paths": present,
        "missing_paths": [p for p in required if p not in present],
        "partial": len(present) not in {0, len(required)},
    }


def _saved_plan_paths(plan: dict[str, Any] | None) -> set[str]:
    """Best-effort extraction of paths the saved plan claims ownership of."""
    if not plan:
        return set()
    paths: set[str] = set()
    # Agents ship via assets/claude/agents/ and deploy_harness deploys them
    # with marker discipline. The plan's recommended-agent list AND the
    # canonical universal roster both surface as on-disk managed paths
    # post-init, so both belong in the saved view to keep
    # _three_way_ownership's missing_from_saved_plan delta truthful. (A
    # recommended agent with no packaged body never surfaces on disk;
    # _three_way_ownership sets those apart -- DEF-756.)
    for agent in plan.get("agents", []) or []:
        if isinstance(agent, dict) and isinstance(agent.get("name"), str):
            paths.add(f".claude/agents/{agent['name']}.md")
    for doc in plan.get("generated_docs", []) or []:
        if isinstance(doc, str):
            paths.add(doc)
    for hook in plan.get("hooks", []) or []:
        if isinstance(hook, dict):
            script = hook.get("script", "")
            if isinstance(script, str) and script.endswith(".py"):
                paths.add(script)
    return paths


def _is_plan_tracked(rel_path: str) -> bool:
    """Paths that the saved plan is expected to enumerate by name.

    Structural files (settings.json, root docs, tool scripts) are always
    managed but are not per-plan entities — they shouldn't trip the
    missing-from-plan drift warning. Skills are deployed and owned but not
    plan-tracked either: the saved plan has no skills source, so counting
    them here would read every fresh init as missing-from-plan.
    """
    # sister-site: ok purpose-scoped: agents+commands only, NOT surface_contract.CLAUDE_SURFACE_KINDS -- the saved plan carries no skills source, so a skill counted here warns on every fresh init
    return (
        rel_path.startswith(".claude/agents/")
        or rel_path.startswith(".claude/commands/")
        or rel_path.startswith("tools/cc/hooks/")
    )


def _packaged_agent_paths() -> set[str]:
    """``.claude/agents/<name>.md`` for every agent body the engine ships.

    The deploy writes agents from the packaged bodies under
    ``espalier/assets/claude/agents/`` and from nothing else, so this is the
    set of agent paths a saved plan can expect on disk. A plan may recommend
    more (``harness_config.OPTIONAL_AGENTS``); those are claims, not deploys.
    """
    from espalier.asset_inventory import packaged_agent_names
    return {f".claude/agents/{name}.md" for name in packaged_agent_names()}


def _recommendable_agent_paths() -> set[str]:
    """``.claude/agents/<name>.md`` for every agent the CURRENT plan builder
    can recommend (``harness_config.DEFAULT_AGENT_ORDER`` + ``OPTIONAL_AGENTS``).

    Distinguishes a recommendation with no packaged body (the builder still
    names it; a re-baseline re-claims it; information) from an agent an older
    engine shipped and this one retired (the builder no longer names it; a
    re-baseline drops it; genuine drift).
    """
    from espalier.harness_config import DEFAULT_AGENT_ORDER, OPTIONAL_AGENTS
    names = [row[0] for row in DEFAULT_AGENT_ORDER] + [row[0] for row in OPTIONAL_AGENTS]
    return {f".claude/agents/{name}.md" for name in names}


def _three_way_ownership(
    repo_root: Path, plan: dict[str, Any] | None
) -> dict[str, list[str]]:
    """Return current / stale / missing-from-plan / unshipped path sets.

    ``stale_saved_paths`` flags any saved-plan path missing from disk — there
    is no tier exemption (every PACKAGED asset deploys to every repo, so a
    saved path absent from disk is genuine drift, cleared by re-running
    ``fingerprint``). ``unshipped_saved_agents`` holds the saved-plan agents
    with no packaged body at all (DEF-756): the plan builder's optional table
    recommends them, no engine since agents began deploying from packaged
    bodies can put them on disk, and reading them as stale left every fresh
    init of an API, ML, UI or ops project in ``warn`` with two remedies that
    re-claimed the same path.
    """
    # current_managed_paths REPORTS disk reality so an adopter sees what
    # the harness actually manages on disk — every tier-deployed agent, and only
    # the docs that exist — matching the self-host path. The drift check below
    # intentionally stays on the PLAN basis (drift_current): a fresh common-tier
    # init records the fingerprint-recommended agents in its saved plan, not the
    # full tier set, so deriving missing_from_saved_plan from disk would falsely
    # warn that the extra deployed agents are "missing from plan" on every clean
    # init (the no-warn-on-fresh-init invariant).
    if surface_contract.is_self_host_repo(repo_root):
        report_current = set(self_host_managed_paths(repo_root))
        drift_current = report_current
    elif plan is not None:
        report_current = set(fallback_managed_paths(repo_root))
        drift_current = set(managed_paths_from_plan(plan))
    else:
        # plan is None and not self-host: no basis to compute ownership.
        # These empty sets mean "could not compute", NOT "computed, found
        # nothing" — downstream stale/missing-from-plan derivations correctly
        # yield empty when there is no plan to diff against.
        report_current = drift_current = set()

    saved = _saved_plan_paths(plan)
    # A saved-plan agent is a recommendation; only one with a packaged body is
    # a deploy the tree can be behind on. A recommended agent with no body
    # was never on disk to be "no longer" there, so it is reported apart; a
    # packaged agent absent from disk stays stale, and so does one the current
    # builder no longer recommends at all (retired by a newer engine: a
    # re-baseline drops it); an adopter-authored body at a recommended path
    # is neither.
    packaged_agents = _packaged_agent_paths()
    recommendable = _recommendable_agent_paths()
    unshipped = {
        p for p in saved
        if p.startswith(".claude/agents/")
        and p not in packaged_agents
        and p in recommendable
        and not (repo_root / p).exists()
    }
    stale = sorted(
        p for p in saved
        if p not in unshipped and not (repo_root / p).exists()
    )
    missing_from_plan = sorted(
        p for p in drift_current
        if _is_plan_tracked(p) and p not in saved and (repo_root / p).exists()
    )
    return {
        "current_managed_paths": sorted(report_current),
        "stale_saved_paths": stale,
        "missing_from_saved_plan": missing_from_plan,
        "unshipped_saved_agents": sorted(unshipped),
    }


def _classify(
    failures: list[str], warnings: list[str]
) -> str:
    if failures:
        return "fail"
    if warnings:
        return "warn"
    return "pass"


def _append_step(next_steps: list[str], text: str) -> None:
    """Append an action unless one naming the same command is already present.

    Two branches can legitimately want the same remedy -- a corrupt
    ``reports/*.json`` trips BOTH the unreadable failure and the
    saved-reports-drift warning, and both want ``fingerprint``. Measured before
    this helper: the report carried the same command twice in different wording,
    which reads as two things to do.

    Dedupes on the first backticked span rather than the whole sentence,
    because the wordings differ; the case-insensitive whole-string dedupe used
    for the recovery forwarding cannot see them. First writer wins, and the
    branches are ordered so the more specific one (which names the offending
    file) runs first.
    """
    start = text.find("`")
    if start != -1:
        end = text.find("`", start + 1)
        if end != -1:
            command = text[start:end + 1]
            if any(command in existing for existing in next_steps):
                return
    next_steps.append(text)


def _primary_reason(
    failures: list[str], warnings: list[str], info: list[str], next_steps: list[str]
) -> str:
    for group in (failures, warnings, info, next_steps):
        if group:
            return group[0]
    return "no issues detected"


def _check_doc_drift(repo_root: Path) -> list[str]:
    """Return human-readable doc-drift findings (empty list = clean).

    Layer 1 of the accuracy stack: numerical claims that can be mechanically
    verified against the live repo. Compares stated counts in CLAUDE.md,
    README.md, and bench/RESULTS.md against the underlying source of truth.

    Used by `espalier doctor --check-doc-drift`. The companion test class
    `tests/test_documented_claims.py::TestClaudeMdHookCounts` covers the same
    pattern at test-time. See `docs/external/README.md` for the broader
    accuracy-layer rationale.
    """
    findings: list[str] = []

    # Hook count claims in CLAUDE.md and README.md. Self-host-gated (R2): this
    # compares a doc's "N hooks" against espalier's OWN canonical roster, which
    # is only meaningful on the harness itself — on an adopter repo it false-
    # warns on unrelated "N hooks" prose (git hooks, React hooks, webhooks). The
    # audit_accuracy sister-site already runs on self-host docs only.
    hooks_dir = repo_root / "tools" / "cc" / "hooks"
    if surface_contract.is_self_host_repo(repo_root) and hooks_dir.is_dir():
        # Count only the *documented* governance hooks by intersecting the
        # glob with the canonical roster. A stray non-canonical .py (e.g. a
        # refactor backup write_guard_backup.py) is not a documented hook and
        # must not inflate the count and emit a spurious drift finding. A
        # missing canonical hook still drops the count (real drift still
        # flags). Sister-site: audit_accuracy.
        _canonical_hooks = set(surface_contract.get_canonical_hook_scripts())
        actual_hooks = len([
            p for p in hooks_dir.glob("*.py")
            if p.name in _canonical_hooks
        ])
        for doc_name in ("CLAUDE.md", "README.md"):
            doc_path = repo_root / doc_name
            if not doc_path.exists():
                continue
            try:
                doc_text = doc_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            # Route through the hardened public helper so doctor inherits
            # the negative-lookbehind, ASCII-only digit class, and re.ASCII
            # flag tightenings. A bare \d+ would match "v10 hooks", "1.10
            # hooks", and fullwidth digits.
            for line in doc_text.splitlines():
                stated = extract_count_for_label(line, "hooks")
                if stated is None or stated == actual_hooks:
                    continue
                findings.append(
                    f"{doc_name} states \"{stated} hooks\" but "
                    # "hook scripts" is the documented count noun; actual_hooks
                    # is the canonical-roster count (12), not the 4
                    # GOVERNANCE_BLOCKING_HOOKS, so "governance hooks" would
                    # mislabel it.
                    f"tools/cc/hooks/ contains {actual_hooks} hook scripts"
                )

    # Test count claims (e.g. "1,431 tests", "1600 cases")
    # We can't cheaply count tests without invoking pytest; skip silently
    # unless a real test count source becomes available.

    # Bench corpus class count claims in bench/RESULTS.md and README.md
    corpus_dir = repo_root / "bench" / "corpus"
    if corpus_dir.is_dir():
        actual_classes = len(list(corpus_dir.glob("BC-[0-9]*.json")))
        for doc_rel in ("bench/RESULTS.md", "README.md"):
            doc_path = repo_root / doc_rel
            if not doc_path.exists():
                continue
            try:
                doc_text = doc_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            # Same sister-site fix as above. The helper's _label_word_re
            # special-cases "bypass classes" multi-word handling
            # (in audit_accuracy.py).
            for line in doc_text.splitlines():
                stated = extract_count_for_label(line, "bypass classes")
                if stated is None or stated == actual_classes:
                    continue
                findings.append(
                    f"{doc_rel} states \"{stated} bypass classes\" but "
                    f"bench/corpus/ contains {actual_classes} files"
                )

    return findings


# Load-bearing external tools the harness assumes are on PATH.
# Adding a new tool here REQUIRES the parity triple, asserted by
# ``tests/test_external_tool_contract.py``:
#
# 1. A dev-extras entry in ``pyproject.toml [project.optional-dependencies].dev``
# 2. A SessionStart warn path in ``tools/cc/hooks/session_start.py``
# 3. A row here in ``_LOAD_BEARING_EXTERNAL_TOOLS``
#
# The install hint is the one-line recovery the doctor / SessionStart
# banner shows the operator. Keep it short and copy-pasteable.
_LOAD_BEARING_EXTERNAL_TOOLS: dict[str, str] = {
    # Lead with the adopter-correct standalone install. `.[dev]` is
    # espalier's OWN dev-extras (only valid in a source checkout); a median
    # `pip install espalier-harness` adopter has no such extras.
    "ruff": "pip install 'ruff>=0.5,<1.0'  # or, in an espalier source checkout: pip install -e '.[dev]'",
}


def _check_external_tool(name: str, install_hint: str) -> list[str]:
    """Probe whether ``name`` resolves via ``shutil.which``.

    Returns a one-line warning when missing, empty list when present.
    Mirrors ``_check_python_resolver``'s ``list[str]`` shape so the
    doctor's warning aggregation stays flat (one source for warnings,
    one source for failures).
    """
    if shutil.which(name) is None:
        return [
            f"load-bearing external tool {name!r} not found on PATH. "
            f"Install via: {install_hint}"
        ]
    return []


def _resolver_hint() -> str:
    """Interpreter name to spell in an operator-facing command.

    Lazy import: ``cli`` imports ``doctor`` at module top, so a top-level
    back-import would be circular.
    """
    from espalier.cli import _detect_python_command
    return _detect_python_command()


def _remedy_hint() -> "tuple[str, bool, str]":
    """``cli._remedy_interpreter()`` plus the names it probed, behind the same
    lazy-import seam as :func:`_resolver_hint`.

    ``(interpreter, resolver_clears_floor, probed_names)``: the interpreter to
    SPELL in a remediation the operator will type (the resolver's answer when
    it clears the floor, else the one running this command), whether the
    resolver's own answer clears the floor (False means ``--rewire-interpreter``
    would find no target on this PATH), and the resolver's candidate names
    rendered for a sentence. Sites that prescribe a command migrate here;
    sites that describe what was WRITTEN keep :func:`_resolver_hint`
    (``DEF-727``; the migration of the remaining sites is ``DEF-758``).
    """
    from espalier.cli import _remedy_interpreter, resolver_candidate_names
    hint, clears = _remedy_interpreter()
    return hint, clears, resolver_candidate_names()


def _remedy_py() -> str:
    """The interpreter to SPELL in a remedy the operator will type:
    ``_remedy_hint()[0]``, behind the same seam so a test can patch either.

    Every ``f"{...} -m espalier ..."`` in this module spells this. The six
    sentences that tell the operator what VALUE to write into settings.json
    by hand (three in the reporter narration, three in the gate next-steps)
    read :func:`_resolver_hint` into a ``written`` local, because a hand edit
    should carry what ``init`` would write -- and each sits in its own
    f-string, apart from the command it follows, because the AST pin in
    ``tests/test_portability_contract.py`` reads an f-string carrying both
    ``-m espalier`` and either resolver (or a local bound from one) as a
    remedy spelled with the write answer (``DEF-758``).
    """
    return _remedy_hint()[0]


def _interpreter_is_python3(path: "str | None") -> bool:
    """Does ``path`` actually ANSWER as a Python 3 interpreter?

    ``shutil.which(name) is not None`` answers "does something answer to this
    name", which is a different question. A Microsoft Store App Execution
    Alias, a stale Python-2 symlink and an unset pyenv shim all satisfy the
    first and fail this one -- and on such a host every hook spawn exits
    outside the ``{0, 2}`` range the hook protocol treats as a decision, so a
    non-decision is non-blocking and every guard fails OPEN while ``init``
    reports success.

    Deliberately a MODULE-LEVEL seam. Tests monkeypatch this rather than
    fabricating filesystem state, because a fixture that patches only
    ``shutil.which`` and hands back a made-up path silently depends on that
    path being a real interpreter on whatever machine runs the suite --
    ``/usr/bin/python3`` is Python 3.9.6 on the author's host and absent on a
    minimal container, so the same fixture means different things in the two
    places.
    """
    if not path:
        return False
    import subprocess
    import sys
    # The process running this code IS a working Python 3. Short-circuiting it
    # removes a subprocess spawn from the common case and, more importantly,
    # removes a FALSE ALARM: on a host where spawning is slow or blocked
    # outright (EDR forbidding child processes), the probe times out, returns
    # False, and reports a healthy host as failing open. Closing a fail-open
    # must not open a fail-closed on the same message.
    try:
        if os.path.samefile(path, sys.executable):
            return True
    except OSError:
        pass
    try:
        result = subprocess.run(
            [path, "--version"], capture_output=True, text=True,
            encoding="utf-8", timeout=2,
        )
    except (subprocess.SubprocessError, OSError, ValueError):  # strict decode: a structured answer (DEF-821)
        return False
    # Through the ONE banner rule, not `startswith("Python 3.")`: the floor
    # parser searches anywhere in the output, and a banner with a line before
    # it split the two readings -- `init` then called one interpreter both
    # "below-floor, guards keep working" and "not Python 3, guards fail OPEN"
    # in one run (DEF-727 review). The hook-side twin reads through its own
    # parity copy of the same rule.
    return is_python3_banner((result.stdout or result.stderr).strip())


# ``_interpreter_meets_floor(path)`` -- does the interpreter at ``path`` clear
# ``_python_floor.MIN_PYTHON``? The capability sibling of
# ``_interpreter_is_python3``, split out for DEF-636: stock /usr/bin/python3 on
# macOS is 3.9.6, which IS a Python 3 and is NOT a Python this package runs on;
# conflating the two questions is what let `doctor` bless a host where the
# blueprint chain was dead in every session. No ``samefile(sys.executable)``
# short-circuit, unlike the identity probe: that shortcut is sound for "is this
# a Python 3" but cannot answer the floor question without assuming its own
# answer -- the version has to be read (pinned on the implementation by
# tests/test_python_floor.py). A module-level ALIAS of the single engine-side
# implementation, kept as a seam so tests monkeypatch this name rather than
# fabricating filesystem state; an alias rather than a one-line wrapper because
# the sister-site probe's alias-call arm reads a wrapper as a re-implementation
# of the hook-side twin, and it was one of the two reds on this repo's own 0-C.
_interpreter_meets_floor = interpreter_meets_floor


def _host_is_windows() -> bool:
    """Seam for the statusLine-fallback host key (tests patch this, not
    ``os.name``, which pathlib reads)."""
    return os.name == "nt"


def espalier_statusline_missing(settings_path: Path, repo_root: Path) -> bool:
    """True when ``settings.json`` parses to an object with no ``statusLine``
    key while ``tools/cc/statusline.py`` is deployed under ``repo_root``
    (DEF-798). The key is the test, and the deployed script is what says it
    is espalier's statusline that is missing (a shim on disk is a file, not a
    wiring). ``doctor``'s fourth statusline note and ``upgrade``'s
    version-current line both read this one predicate, so the two narrators
    of a tree cannot disagree about it; the merge's own question -- add the
    key? -- is ``cli._would_add_statusline``, script-blind on purpose (wiring
    ahead of a deploy is a legitimate move, DEF-427). A present key of any
    value is the operator's; a file that cannot be read has its own
    reporters; both read False."""
    try:
        settings = json.loads(surface_contract.decode_bom(settings_path.read_bytes()))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return False
    if not isinstance(settings, dict) or "statusLine" in settings:
        return False
    script = surface_contract.path_presence(repo_root / STATUSLINE_SCRIPT)[0]
    return script == surface_contract.PRESENCE_PRESENT


def _statusline_fallback_notes(settings_path: Path, repo_root: Path) -> list[str]:
    """Info lines about the interpreter-missing fallback in ``statusLine``.

    ``cli._statusline_command`` renders ``<interp> "<script>" || echo '...'``
    on a POSIX host (DEF-508) and ``"<shim>" <interp>`` on Windows, the batch
    shim ``tools/cc/statusline.cmd`` carrying the same fallback (DEF-729).
    The merge adds the key only when it is absent and the rewire swaps the
    interpreter the string names (DEF-798, DEF-810), so the string an install
    carries can disagree with the host it runs on in three ways, and a fourth
    state has no string at all:

    * Either host, neither the clause nor the shim -- rendered before the
      fallback existed: when the wired interpreter stops resolving the
      statusline goes blank instead of saying so. A fresh ``init`` renders
      ``settings.json.new`` beside the file when the render differs; the
      operator takes its ``statusLine``.
    * Windows host, clause present -- rendered on another host and carried in
      by a tracked ``settings.json`` (DEF-11): under Windows PowerShell
      without Git Bash the line cannot parse and the statusline goes blank on
      a healthy install. The remedy is the one-line hand edit.
    * POSIX host, shim head -- rendered on Windows and carried in the same
      way: a POSIX shell cannot run a ``.cmd``, so the statusline goes blank
      on a healthy install. A fresh ``init`` renders the POSIX string.
    * Either host, no ``statusLine`` key while ``tools/cc/statusline.py`` is
      deployed -- wired by ``--wire-hooks`` or ``merge-settings`` before the
      merge learned to add the key (DEF-798), or a hand-kept file: the harness
      statusline is off, and nothing says so when the interpreter goes
      missing. ``merge-settings`` adds the key on request and never touches a
      statusLine of the operator's own. Without the script there is no
      espalier statusline to miss, and the key is theirs.

    Info, never a warning: no shape breaks a guard. Only espalier's own
    statusline (one naming ``tools/cc/statusline.py`` or headed by the shim)
    is examined; an operator's own statusLine is theirs.
    """
    try:
        settings = json.loads(surface_contract.decode_bom(settings_path.read_bytes()))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return []
    if not isinstance(settings, dict):
        return []
    if "statusLine" not in settings:
        # DEF-798: one predicate with upgrade's version-current line. A present
        # key of any value is the operator's and is read below on its own terms.
        if espalier_statusline_missing(settings_path, repo_root):
            return [
                "settings.json has no statusLine while tools/cc/statusline.py is "
                "deployed (wired before the merge learned to add the key, or a "
                "hand-kept file): the harness statusline is off, and when the "
                "wired interpreter goes missing nothing says so. "
                f"`{_remedy_py()} -m espalier merge-settings .` adds espalier's "
                "statusLine when the key is absent and never touches one of "
                "your own (set the key to null to keep the statusline off)."
            ]
        return []
    status_line = settings.get("statusLine")
    if not isinstance(status_line, dict):
        return []
    command = status_line.get("command")
    if not isinstance(command, str):
        return []
    runs_script = STATUSLINE_SCRIPT in command.replace("\\", "/")
    runs_shim = is_statusline_shim_head(interpreter_token(command))
    if not (runs_script or runs_shim):
        return []
    has_clause = " || " in command
    if _host_is_windows():
        if runs_shim and not has_clause:
            return []
        # A shim head that ALSO carries the clause (a half-taken hand edit,
        # a merge of two generations) cannot parse under Windows PowerShell
        # either: the clause note below is the right one.
        if has_clause:
            return [
                "statusLine.command carries a POSIX `||` fallback clause, so it was "
                "rendered on another host: under Windows PowerShell without Git "
                "Bash the line cannot parse and the statusline goes blank on a "
                "healthy install. Delete everything from ` || ` to the end of the "
                "statusLine command in .claude/settings.json."
            ]
    elif runs_shim:
        return [
            f"statusLine.command runs the Windows shim {STATUSLINE_SHIM}, so it "
            "was rendered on Windows and carried in: a POSIX shell cannot run it "
            "and the statusline goes blank on a healthy install. "
            f"`{_remedy_py()} -m espalier init .` renders "
            ".claude/settings.json.new beside your file; take its statusLine line."
        ]
    elif has_clause:
        return []

    return [
        "statusLine.command has no interpreter-missing fallback (rendered "
        "before it existed): when the wired interpreter stops resolving the "
        "statusline goes blank instead of saying so. "
        f"`{_remedy_py()} -m espalier init .` renders "
        ".claude/settings.json.new beside your file; take its statusLine line."
    ]


def _check_python_resolver(
    repo_root: Path, settings_path: Path | None = None
) -> list[str]:
    """Verify the python interpreter named in ``.claude/settings.json`` resolves
    on the current host. Returns a list of warning strings (empty if no issue).

    Reads ``hooks[*].hooks[*].command`` from settings.json; for python-like
    names (``python``, ``python3``, ``python3.12``, ``py``), runs
    ``shutil.which(name)``. If which returns None, emits a warning naming the
    missing interpreter and the resolution hint (Windows ``py -3`` shim, macOS
    ``python`` symlink). Cross-platform interpreter-resolver gap: Windows hosts
    typically ship ``python.exe`` not ``python3``, so settings generated on a
    Unix host can silently fail to spawn hooks on Windows.
    """
    issues: list[str] = []
    sp = settings_path or (repo_root / ".claude" / "settings.json")
    if not sp.is_file():
        return issues
    try:
        # decode_bom (UTF-8/16/32 BOM-tolerant), consistent with the other
        # settings.json readers — a BOM must not suppress this check.
        settings = json.loads(surface_contract.decode_bom(sp.read_bytes()))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return issues
    # A valid-JSON non-dict settings (`[]`/`"s"`/`42`) parses cleanly, then
    # settings.get(...) would raise AttributeError past the JSONDecodeError
    # handler → run_doctor_check crashes (a fail-open).
    if not isinstance(settings, dict):
        return issues
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        return issues
    seen_commands: set[str] = set()
    for event_hooks in hooks.values():
        if not isinstance(event_hooks, list):
            continue
        for hook_entry in event_hooks:
            if not isinstance(hook_entry, dict):
                continue
            for inner in hook_entry.get("hooks", []) or []:
                if not isinstance(inner, dict):
                    continue
                cmd = inner.get("command", "")
                if isinstance(cmd, str) and cmd:
                    # TOKENIZE, exactly as the statusLine arm below already
                    # does. These used to be added whole, so on the LEGACY
                    # SHELL FORM -- `python tools/cc/hooks/write_guard.py`,
                    # which is DEF-620's own measured population -- this reader
                    # and `cli.rewire_interpreter_in_settings` disagreed about
                    # what "the interpreter" is. The rewire fixed argv[0]; this
                    # kept warning about the whole string, so the operator loop
                    # was: doctor complains -> rewire -> doctor complains
                    # identically -> rewire says "nothing to do" -> forever.
                    # Two readers of one file must agree on argv[0].
                    token = interpreter_token(cmd)
                    if token and "${" not in token and not token.endswith((".py", ".sh")):
                        seen_commands.add(token)
    # statusLine is the 13th interpreter site and lives outside ``hooks``.
    # It is a shell string, so take argv[0] -- or argv[1] behind the Windows
    # statusline shim (DEF-729), through the helper the rewire reads too; a
    # brought-your-own settings.json may have no statusLine key at all.
    status_line = settings.get("statusLine")
    if isinstance(status_line, dict):
        status_cmd = status_line.get("command")
        if isinstance(status_cmd, str) and status_cmd.strip():
            token = interpreter_site_token(status_cmd)
            # A bare-PATH script (``${CLAUDE_PROJECT_DIR}/...`` or a ``.py``)
            # is run via its shebang, not looked up on PATH -- `which` always
            # answers None for it, so checking it would warn every run on a
            # config that is fine.
            if token and "${" not in token and not token.endswith((".py", ".sh")):
                seen_commands.add(token)

    python_like = {
        c for c in seen_commands
        if c == "python" or c == "py" or c.startswith("python")
    }
    # Identity, not presence. Under a stub this used to be True, so doctor
    # emitted "`python3` IS on PATH -- re-run init" -- actively WRONG advice
    # on the exact host this check exists for.
    py3_present = _interpreter_is_python3(shutil.which("python3"))
    for cmd in sorted(python_like):
        if resolves_only_inside(cmd):
            # The name RESOLVES for the shell doctor is standing in, and is
            # still broken: it is a virtualenv shim that vanishes with the
            # shell, while settings.json outlives it. Deliberately NOT folded
            # into the branch below -- that hint offers "symlink <cmd> ->
            # python3", and here `python3` is the venv's own, so following it
            # makes the breakage permanent.
            root = venv_root_of(shutil.which(cmd) or "") or Path(
                os.environ.get("VIRTUAL_ENV", "")
            )
            issues.append(
                f"hook interpreter `{cmd}` resolves only inside the virtualenv "
                f"at `{root}`. Hooks spawn under the PATH Claude Code is "
                f"launched with, which will not have this virtualenv activated "
                f"-- they will fail to start and every blocking guard fails "
                f"open. Re-run `{_remedy_py()} -m espalier init . --rewire-interpreter` "
                f"from a shell with the virtualenv deactivated so a host-wide "
                f"interpreter name is wired."
            )
        else:
            # THREE states, not two. The old `elif which(cmd) is None` collapsed
            # "absent" and "present but not Python" into one test that only
            # caught the first -- so on a stub host NO branch fired at all and
            # doctor reported nothing while every guard was failing open.
            resolved = shutil.which(cmd)
            if resolved is None:
                problem = (
                    f"hook interpreter `{cmd}` does not resolve on current host. "
                )
            elif not _interpreter_is_python3(resolved):
                problem = (
                    f"hook interpreter `{cmd}` resolves to `{resolved}` but does "
                    f"not answer as Python 3, so every hook spawned with it exits "
                    f"outside the blocking range and each guard fails OPEN while "
                    f"init reports success. "
                )
            elif not _interpreter_meets_floor(resolved):
                # FOUR states, not three (DEF-636). "Is a Python 3" and "is a
                # Python this package runs on" are different questions, and the
                # remedy differs too: the branch above offers "symlink cmd ->
                # python3", which on a 3.9-only host makes the breakage
                # permanent. Here the only real fix is a newer interpreter.
                problem = (
                    f"hook interpreter `{cmd}` resolves to `{resolved}` and IS "
                    f"Python 3, but is older than the {floor_text()} this "
                    f"package requires. The blocking guards keep working, so "
                    f"nothing visibly fails -- while the blueprint chain, Gate 4 "
                    f"finalize and subagent-reasoning capture spawn a file that "
                    f"raises SyntaxError every session. Install Python "
                    f"{floor_text()} or newer and re-wire the hooks to it. "
                )
            else:
                continue  # resolves, is Python 3, clears the floor.
            # DEF-620, one more time: do not prescribe `--rewire-interpreter`
            # for a site that verb will DECLINE. `py -3` (launcher flags) and
            # an unterminated quote are refused there by design, so pointing at
            # the flag would send the operator round the same loop the flag was
            # added to end. Ask the one predicate that decides, so the two
            # cannot drift.
            from espalier.cli import (  # lazy: cli imports doctor at top level
                _is_rewirable_interpreter,
            )
            if not _is_rewirable_interpreter(cmd):
                issues.append(
                    problem
                    + f"`{_remedy_py()} -m espalier init . "
                    "--rewire-interpreter` will NOT fix this one -- it declines "
                    "command shapes that are not a bare interpreter (the `py` "
                    "launcher, an unterminated quote, a shebang script). Edit "
                    "this command in .claude/settings.json by hand."
                )
                continue
            if py3_present:
                # The common case -- `python3` IS on PATH but settings
                # wired a different name (e.g. `python`) or a stale path.
                # Re-init/symlink is the real fix, not installing python.
                hint = (
                    f"a WORKING `python3` IS on PATH -- re-run "
                    f"`{_remedy_py()} -m espalier init . --rewire-interpreter` "
                    f"to rewire the wired interpreter, or symlink `{cmd}` -> "
                    f"python3."
                )
            else:
                hint = (
                    "no working `python3` on PATH either -- on Windows try "
                    "`py -3` or create a `python3` shim (an App Execution Alias "
                    "resolves but is not an interpreter); on macOS install via "
                    "`brew install python`."
                )
            issues.append(problem + hint)
    return issues


# Repo mode constants and detector live in ``espalier.repo_mode`` so
# self-host, release_check, and any future command can share them. doctor
# re-exports for backward compatibility: ``doctor.REPO_MODE_*`` and
# ``doctor._detect_repo_mode`` continue to work (the ``as _detect_repo_mode``
# alias preserves the private-helper name used internally by
# ``run_doctor_check`` below).
from espalier.repo_mode import (  # noqa: E402
    REPO_MODE_INITIALIZED_CONSUMER,  # read by the uninstalled branch; also a backward-compat re-export (cli.py)
    REPO_MODE_INITIALIZED_SELF_HOST,  # noqa: F401  backward-compat re-export (cli.py)
    REPO_MODE_SOURCE_CHECKOUT,
    REPO_MODE_UNINITIALIZED,
    detect_repo_mode as _detect_repo_mode,
    runtime_marker_paths,
)


# The merge-settings remedy phrasing embedded in the consolidated line.
# Uses `<interp> -m espalier` (NOT bare `espalier`) — the engine runs as a
# module in a fusion, where bare `espalier` is command-not-found
# (tests/test_no_bare_espalier_hints.py pins this for engine runtime strings).
# The interpreter is resolved on the host (python vs python3) — same detection
# the harness uses to wire settings.json — so this is a function, not an
# import-time constant (detection must run per-host, not at module load).
def _merge_settings_remedy() -> str:
    """``run `<interp> -m espalier merge-settings``` — interpreter resolved on the host."""
    return f"run `{_remedy_py()} -m espalier merge-settings`"


def _consolidated_unwired_line(scripts: list[str]) -> str:
    """The single fail-closed line that replaces the N near-identical per-gate
    failures when settings.json is readable+valid but wires zero Espalier hooks.

    Keep fail-closed — status stays ``fail`` and EVERY unwired gate is still
    named (so the deleted-event completeness contract holds) — but stop the
    wall of N identical lines that contradicts the honest exit-0 ``init``
    banner, and point at the ``merge-settings`` remedy. Contains the literal
    ``governance gate`` token so the ``_governance_failures`` consumer still
    matches it."""
    return (
        f"{plural(len(scripts), 'governance gate')} not effectively wired: "
        + ", ".join(scripts)
        + " present on disk but .claude/settings.json wires no Espalier "
        "hooks — " + _merge_settings_remedy() + " to wire them"
    )


def _is_benign_hookless_settings(settings_path: Path) -> bool:
    """True for the benign brought-your-own onboarding state: settings.json is
    READABLE+valid-dict and references NO canonical ``tools/cc/hooks/`` path at
    all (the adopter never added the Espalier hooks). False for a
    present-but-unreadable settings (dangling symlink / malformed → genuine
    problem) AND for one that references the hooks but leaves them
    unwired/neutered/inert (a tamper/stale signal that must stay loud)."""
    if not os.path.isfile(settings_path):  # dangling symlink / absent / unreachable → not benign
        return False
    try:
        # BOM-tolerant: a UTF-16 settings.json is what Windows PowerShell writes
        # by default, and reading it as plain UTF-8 made a perfectly valid file
        # look malformed -- a loud false alarm on an adopter who did nothing
        # wrong. Genuinely malformed content still falls through below.
        parsed = json.loads(surface_contract.decode_bom(settings_path.read_bytes()))
    except (OSError, ValueError):  # malformed → genuine problem, stay loud
        return False
    if not isinstance(parsed, dict):
        return False
    # A value-marker kill-switch (disableAllHooks / bypassPermissions) is NOT
    # benign onboarding: the soft "brought-your-own — run merge-settings" remedy
    # would wire hooks the kill-switch still disables at runtime. Fall through to
    # the loud per-gate branch so the report names the real tamper. Reuse the
    # shared marker helper so this stays parity-locked with the C-3 live check.
    from espalier.selfcheck import _find_kill_switch_markers
    if _find_kill_switch_markers(".claude/settings.json", parsed):
        return False
    if "hooks" not in parsed:
        # No hooks section at all — a genuine brought-your-own settings.json.
        return True
    hooks = parsed["hooks"]
    if not isinstance(hooks, dict):
        # hooks present but malformed (str / list / null) — NOT a clean
        # brought-your-own; the deleted-event fail-closed contract owns this
        # (a corrupted/neutered hooks value must flag every gate, loud).
        return False
    # Normalize separators before the canonical-path check (CLAUDE.md
    # Architecture Rule: path comparisons use ``.replace("\\", "/")`` for Windows
    # compat). Without it a backslash-path neutered gate (`...\tools\cc\hooks\…`)
    # would read as "no canonical reference" → false-benign, softening a tamper.
    return "tools/cc/hooks/" not in json.dumps(hooks).replace("\\\\", "/").replace("\\", "/")


def _check_reporter_hook_wiring(repo_root: Path) -> list[str]:
    """A WARNING per reporter-tier hook whose file is on disk but whose wiring
    is not executable under its canonical event (DEF-619).

    The blocking oracle below is pinned to the four gates on purpose (count
    parity with ci_guard), which left the eight reporters outside every check:
    both variants were driven on 2026-08-27 -- the two recall-engine events
    deleted, or their commands set to ``echo`` -- and ``init`` still claimed
    "Hooks now intercept" while ``doctor`` stayed at pass. A dead reporter
    fails nothing visibly, which is the whole reason it needs saying:
    subagents start cold, a failed edit gets no re-derivation nudge,
    compaction loses its re-injection.

    Warnings, never failures: nothing that denies is missing, and the failure
    count must stay parity-locked with ``ci_guard``. Empty when settings.json
    is absent (presence owns that) and on a voided file (the governance
    failure already says no hook loads at all). The remedy is shape-keyed and
    rides in the line, because only ``GATE_ABSENT`` has a command -- and even
    that one is withheld on a file the merge would refuse (the DEF-700 class).
    """
    from espalier import harness_config
    settings_path = repo_root / ".claude" / "settings.json"
    if not _settings_reaches_a_read(settings_path):
        return []
    if surface_contract.hooks_config_voided_by(
        surface_contract._load_settings_hooks_cfg(repo_root)
    ) is not None:
        return []
    shapes = harness_config.group_unwired_reporters_by_shape(repo_root)
    if not shapes:
        return []
    from espalier import cli as _cli  # lazy: cli imports doctor at top level
    # A file the merge refuses whole for a reason ABOVE the event level --
    # unreadable, unparseable, not an object, a hooks block that is not one --
    # has no entry an operator could add or fix, and the required-file failure
    # already says "move it aside and re-run init". Eight per-hook remedies
    # none of which can be followed would only bury that line (driven by the
    # failure-mode pass on a truncated settings.json).
    merge_refused = _merge_would_be_refused(repo_root)
    if merge_refused and merge_refused.split(":", 1)[0] in {
        _cli.MERGE_REFUSED_UNREADABLE, _cli.MERGE_REFUSED_UNPARSEABLE,
        _cli.MERGE_REFUSED_NOT_OBJECT, _cli.MERGE_REFUSED_HOOKS_BLOCK,
    }:
        return []
    py = _cli._remedy_py()
    written = _resolver_hint()  # the value init WRITES: what a hand edit carries (DEF-758)
    warnings: list[str] = []
    for shape, scripts in sorted(shapes.items()):
        for script in scripts:
            event = harness_config.GATE_EVENT_OF(script)
            job = harness_config.CANONICAL_HOOK_WIRING[script]["reason"]
            if shape == harness_config.GATE_LEGACY_FORM:
                # Its own sentence, because it is not dead: the shell form is
                # one this check cannot READ, and the gate-side claim forgives
                # the same shape. The remedy is a hand edit to exec form --
                # NOT `--rewire-interpreter`, which swaps argv[0] of a bare
                # interpreter and declines a shell string (the DEF-620 loop,
                # driven again by the failure-mode pass on a shell-form tree).
                warnings.append(
                    f"reporter hook wired in a form this check cannot verify: "
                    f"{script} sits under the {event!r} event in the pre-v0.6.5 "
                    f"shell form and most likely fires (its job: {job}). To make "
                    f"it verifiable, `{py} -m espalier merge-settings . --repair` "
                    f"converts it to exec form (backup first), or edit the entry "
                    + f"by hand: command `{written}`, script path in args."
                )
                continue
            if shape == harness_config.GATE_ABSENT:
                remedy = (
                    f"the {event!r} event is missing from the file; "
                    + (
                        f"add it by hand (the merge would refuse this file: "
                        f"{merge_refused})"
                        if merge_refused else
                        f"`{py} -m espalier merge-settings .` adds it"
                    )
                )
            elif shape == harness_config.GATE_ORPHANED:
                remedy = (
                    f"the {event!r} event exists but carries no entry for it, "
                    "and plain merge-settings adds nothing inside an existing "
                    f"event -- `{py} -m espalier merge-settings . --repair` adds "
                    f"the entry (backup first), or add it by hand (command "
                    + f"`{written}`, script path in args)"
                )
            elif shape == harness_config.GATE_INERT:
                remedy = (
                    "the entry names the script but runs no interpreter -- "
                    f"`{py} -m espalier merge-settings . --repair` rewrites it "
                    + f"(backup first), or set its command back to `{written}` with "
                    "the script path in args by hand"
                )
            elif shape == harness_config.GATE_MISWIRED:
                canonical_matcher = harness_config.CANONICAL_HOOK_WIRING[script]["matcher"]
                remedy = (
                    f"it is {harness_config.miswiring_detail(repo_root, script)} "
                    f"-- `{py} -m espalier merge-settings . --repair` puts it "
                    f"back under {event!r} with "
                    + (f"matcher {canonical_matcher!r}" if canonical_matcher
                       else "no matcher")
                    + " (backup first), or edit the entry by hand"
                )
            else:
                remedy = "inspect its entry in .claude/settings.json by hand"
            warnings.append(
                f"reporter hook not wired: {script} is on disk but has no "
                f"executable, correctly-matched wiring under the {event!r} "
                f"event in .claude/settings.json, so its job ({job}) is "
                f"silently not done -- it never blocks, which is why nothing "
                f"failed visibly. Remedy: {remedy}."
            )
    return warnings


def _check_governance_event_wiring(repo_root: Path) -> list[str]:
    """A blocking governance hook whose *file* is on disk but whose gate has
    been removed or neutered in ``.claude/settings.json`` is a silent
    fail-open — the DENY gate is gone, yet every presence/audit signal
    stays green (the kill-switch scan only flags PRESENT-but-empty keys; a
    deleted key never enters its loop).

    Returns a FAILURE for each blocking hook (``harness_config.
    GOVERNANCE_BLOCKING_HOOKS``) present on disk under ``tools/cc/hooks/`` whose
    gate is not *executably* wired under its canonical event. "Executably
    wired" requires an entry that: runs the script via a python interpreter
    (not ``true``/``:``/``echo``/a ``#``-commented or wrong-``type`` entry that
    leaves the path as bait); points at the canonical
    ``tools/cc/hooks/<script>`` path (not a stale copy sharing the basename);
    and — for PreToolUse hooks — carries a matcher that actually fires on
    Write/Edit/NotebookEdit. Keying on file-on-disk models the disarm mechanism
    ("the scripts stay on disk") and avoids false-positives on a repo that never
    installed the harness. Empty when ``.claude/settings.json`` is absent — the
    presence check owns "settings.json missing"."""
    from espalier import harness_config  # local: keep import-time graph acyclic
    settings_path = repo_root / ".claude" / "settings.json"
    # A DANGLING symlink (lexists True, exists False — e.g. settings.json -> a
    # per-machine file absent on CI) is present-but-unreadable, not absent.
    # Treat it like a malformed file (fall through → flag the deployed gates),
    # not "settings absent → init owns it".
    if not _settings_reaches_a_read(settings_path):
        return []
    # The PREDICATE lives in harness_config (one home, two engine-side callers:
    # this reporter and cli's enforcement-claim check). Keeping a second copy
    # of the loop here would be a fresh sister_site_probe clique in espalier/*,
    # costing one of the last opt-out slots to say nothing new. What stays here
    # is the PROSE, which is doctor's alone.
    failures: list[str] = []
    # ⚠ PREPENDED, and it must stay on BOTH sides of the parity lock. ci_guard's
    # twin emits the same summary line into its `findings`; adding it to only
    # one side splits `len(doctor) == len(ci)` on exactly the tree the summary
    # exists for -- the "doctor closed, ci open" one-directional drift that this
    # oracle's own lineage was written to end. It was introduced here, caught by
    # review, and reproduced at 4-vs-5 before being closed.
    # It leads because `_primary_reason` surfaces failures[0]: on a voided file
    # the per-gate lines below are all true and all unactionable, and the entry
    # that killed them may be one espalier does not manage.
    voided_by = surface_contract.hooks_config_voided_by(
        surface_contract._load_settings_hooks_cfg(repo_root)
    )
    if voided_by:
        failures.append(
            f"governance hooks are not loaded at all: {voided_by} -- Claude "
            'Code discards the WHOLE hooks block unless every entry sets '
            '"type": "command", so the gates below cannot fire whatever their '
            "own wiring says"
        )
    for script in harness_config.unwired_governance_gates(repo_root):
        event = harness_config.GOVERNANCE_BLOCKING_HOOKS[script]
        failures.append(
            f"governance gate not effectively wired: {script} is present on "
            f"disk but has no executable, correctly-matched wiring under the "
            f"{event!r} event in .claude/settings.json "
            + (
                # ⚠ On a voided tree the generic cause list is FALSE for every
                # gate, and it contradicts the finding printed directly above
                # it in the same block -- two adjacent lines disagreeing is
                # harder to catch than one wrong line. `a wrong 'type'` also
                # left the list entirely: a bad type never disables ONE gate,
                # it voids the file, which is its own finding now.
                "(the whole hooks block is void -- see the first finding above)"
                if voided_by else
                "(a deleted event key, a no-op/echo/commented command, a "
                "stale-copy path, or a tool-excluding matcher silently "
                "disables the gate)"
            )
        )
    # NB: this oracle stays PER-GATE — it is count-parity-locked with
    # ci_guard's `_scan_settings_for_missing_governance_events`
    # (tests/test_ci_guard.py::test_doctor_ci_scan_parity_on_malformed_settings
    # pins `len(doctor) == len(ci) == 4`). The benign-hookless CONSOLIDATION
    # (collapse the wall to one fail-closed line + merge-settings pointer) is a
    # PRESENTATION concern handled in `run_doctor_check`, NOT here — so the seam
    # stays locked while the interactive report stops the wall-of-red.
    return failures


def _merge_would_be_refused(repo_root: Path) -> str | None:
    """Why ``merge-settings`` would refuse this tree outright, or ``None``.

    ``doctor`` offers ``merge-settings`` from TWO arms -- the benign-hookless
    consolidation and the partial-disarm absent arm -- and both named it on
    files the merge refuses whole. Driven 2026-08-27: with
    ``hooks.PreToolUse`` set to a string, both arms printed "run merge-settings"
    and the merge returned ``bad_hooks`` having written nothing.

    ⚠ The predicate is ``cli._merge_refusal_detail`` -- ONE home, two direct
    callers (cli's banner and this helper) serving THREE offer sites, because a
    copy of the refusal rule here would be free to drift
    from the merge it describes, which is how the offer became false in the
    first place. Best-effort by design: this is a diagnostic, and losing the
    check costs a caveat, never correctness of the findings themselves.
    """
    from espalier import cli as _cli  # lazy: cli imports doctor at module load
    # ⚠ Driven 2026-09-06 (DEF-700) on a settings.json truncated to 0 bytes:
    # this predicate used to parse inside a blanket `except` that returned
    # None, so BOTH offer arms printed "run merge-settings" and the merge
    # exited 1 with "could not parse". The file-level predicate now lives
    # beside the value-level one in cli, where the init and fuse banners can
    # ask it too (the review found both offering the same refused merge).
    return _cli.merge_refusal_for_file(
        repo_root / ".claude" / "settings.json", repo_root
    )


def _merge_refusal_step(refused: str, py: str) -> str:
    """The next step to print INSTEAD of ``merge-settings`` when the merge
    would refuse the file. Thin delegate to :func:`cli.merge_refusal_step`,
    the one renderer every offer site shares."""
    from espalier import cli as _cli  # lazy: cli imports doctor at module load
    return _cli.merge_refusal_step(refused, py)


def _unreadable_report(repo_root: Path, detail: str) -> dict[str, Any]:
    """``.claude`` is a directory this process cannot search or list. One
    failure naming the permission and the remedy -- never the list every
    deployed file would otherwise appear on as "missing", and never ``init``,
    which cannot write into that directory either. The mode is not detected:
    detection reads ``.claude``."""
    from espalier.repo_mode import DOCTOR_MODE_UNREADABLE  # the vocabulary's one home

    py = _remedy_py()
    sentence = surface_contract.unreadable_root_sentence(detail)
    return {
        "status": "fail",
        "mode": DOCTOR_MODE_UNREADABLE,
        "repo_root": str(repo_root),
        "primary_reason": sentence,
        "message": sentence,
        "next_steps": [f"{sentence} `{py} -m espalier doctor .`"],
        "warnings": [],
        "failures": [sentence],
        "info": [],
        "doc_drift": [],
    }


def _uninitialized_report(repo_root: Path, detected_mode: str) -> dict[str, Any]:
    """Fresh, never-initialized repo: friendly first-run guidance, not a
    JSON failure dump."""
    py = _remedy_py()  # the interpreter to spell in a remedy (DEF-758)
    return {
        "status": "uninitialized",
        "mode": detected_mode,
        "repo_root": str(repo_root),
        "primary_reason": "repo has not been initialized for Espalier-Harness",
        "message": (
            "This repo has not been initialized for Espalier-Harness yet. "
            f"Run `{py} -m espalier init .` to set up the governance harness."
        ),
        "next_steps": [f"{py} -m espalier init ."],
        "warnings": [],
        "failures": [],
        "info": [f"repo is uninitialized; run `{py} -m espalier init .` to set up"],
        "doc_drift": [],
    }


def _deployed_surface_remains(repo_root: Path, plan: dict[str, Any] | None) -> bool:
    """True while anything the harness deploys under a harness-owned root is
    still on disk, or ``.claude/settings.json`` still executes an Espalier
    hook. False is the state ``clean-generated --execute`` leaves.

    Two derivations, unioned, never a typed list of what the uninstall
    removes: the saved plan's inventory (``managed_paths_from_plan``, on an
    empty plan when the plan file is gone too) and disk reality under the
    same roots (``fallback_managed_paths``, which reads every ``.claude/``
    kind through the contract's one owner -- the plan never lists skills,
    so the plan alone read a tree with nine leftover ``SKILL.md`` files as
    uninstalled; the failure-mode review drove it). The root docs, the seed
    docs and the two reports lie outside ``HARNESS_OWNED_ROOTS`` and are
    kept by the uninstall by contract, so their presence says nothing here;
    ``.claude/settings.json`` lies inside one and is kept unwired, so it is
    read for its wiring rather than its existence. An unreadable or
    malformed settings.json reads as "wires nothing" here, the same as an
    absent one: with no deployed surface on disk the tree is uninstalled
    either way, and the file is the adopter's to repair.
    """
    from espalier.cli import _settings_has_espalier_hooks  # lazy: cli imports doctor at top level
    candidates = set(managed_paths_from_plan(plan or {})) | set(fallback_managed_paths(repo_root))
    for rel in sorted(candidates):
        if rel in STANDARD_MANAGED_SETTINGS:
            continue
        under_owned_root = any(
            rel == root or rel.startswith(root + "/") for root in HARNESS_OWNED_ROOTS
        )
        if under_owned_root and (repo_root / rel).exists():
            return True
    hooks_cfg = surface_contract._load_settings_hooks_cfg(repo_root)
    return hooks_cfg is not None and _settings_has_espalier_hooks({"hooks": hooks_cfg})


def _uninstall_leftovers(repo_root: Path) -> list[str]:
    """The harness-owned runtime files still on disk after an uninstall: the
    markers the mode detector reads (minus ``.claude/settings.json``, which
    the uninstall unwires and leaves as the adopter's) and the saved reports.
    Present paths only, in a stable order, each named once. Empty once they
    are gone -- the caller then reports the tree as never initialized, so
    the advice to delete them is terminal (the code review drove the first
    draft round-tripping to the fail verdict: the plan file gone, the
    branch's own precondition with it)."""
    named: list[str] = []
    for rel in (*runtime_marker_paths(), *surface_contract.get_managed_report_paths()):
        if rel in STANDARD_MANAGED_SETTINGS or rel in named:
            continue
        if (repo_root / rel).exists():
            named.append(rel)
    return named


def _uninstalled_report(
    repo_root: Path, detected_mode: str, leftovers: list[str],
) -> dict[str, Any]:
    """A saved plan whose deployed surface is gone: ``clean-generated
    --execute`` ran, or an init never finished. Reported with the
    never-initialized status (CI keys on the same exit 0) and the same
    reinstall step, plus the files left behind and the step that finishes
    the uninstall. Until 2026-09-12 this tree fell to the saved-plan branch
    -- ``fail``, "missing required managed surface", every removed hook
    script listed as a stale plan path -- for an adopter confirming the
    uninstall took (DEF-770).
    """
    hint, _clears, _probed = _remedy_hint()
    named = ", ".join(leftovers)
    return {
        "status": "uninitialized",
        "mode": detected_mode,
        "repo_root": str(repo_root),
        "primary_reason": (
            "harness not on disk: nothing it deploys is present (uninstalled, "
            f"or an init that did not finish); runtime state still here: {named}"
        ),
        "message": (
            "The harness is not on this tree; the runtime state clean-generated "
            f"keeps by contract still is: {named}. "
            f"Run `{hint} -m espalier init .` to reinstall. Removing it for "
            "good: delete those files; .claude/settings.json is yours and stays "
            "(left unwired), and the docs init seeded are listed under "
            "preserved_user_files in clean-generated's report."
        ),
        "leftovers": list(leftovers),
        "next_steps": [
            f"{hint} -m espalier init .   (reinstall)",
            f"removing the harness for good: delete {named} (runtime state "
            "clean-generated keeps by contract); .claude/settings.json is yours "
            "and stays, left unwired; the docs init seeded are listed under "
            "preserved_user_files in clean-generated's report",
        ],
        "warnings": [],
        "failures": [],
        "info": [f"harness not on disk; runtime state still here: {named}"],
        "doc_drift": [],
    }


def _source_checkout_report(
    repo_root: Path, detected_mode: str, presence: dict[str, Any]
) -> dict[str, Any]:
    """Committed surface present but no runtime artifacts yet. Skip the
    auxiliary-required-paths check (init-generated) and the self-host gate;
    still run the governance-event wiring oracle (it self-guards on
    settings.json existence)."""
    py = _remedy_py()  # the interpreter to spell in a remedy (DEF-758)
    committed_required = [
        p for p in presence["required"]
        if p not in AUXILIARY_REQUIRED_PATHS
    ]
    committed_present = [
        p for p in committed_required if (repo_root / p).exists()
    ]
    committed_missing = [
        p for p in committed_required if not (repo_root / p).exists()
    ]
    failures: list[str] = []
    warnings: list[str] = []
    # source-checkout normally has no settings.json (a runtime artifact), so
    # this is a no-op on a true fresh clone — but `--mode source-checkout` can
    # be forced on a repo that DOES have a present-but-neutered settings.json.
    # The governance oracle self-guards on settings.json existence, so run it
    # here too rather than let the early-return skip a dead gate.
    failures.extend(_check_governance_event_wiring(repo_root))
    if committed_missing:
        # Missing committed surface IS a real failure even in
        # source-checkout mode — those files should be in source control.
        failures.append(
            f"missing committed managed surface: {committed_missing}"
        )
    return {
        "status": "fail" if failures else "pass",
        "mode": detected_mode,
        "repo_root": str(repo_root),
        "primary_reason": (
            failures[0] if failures
            else "source checkout -- local runtime files not yet generated; "
                 f"run `{py} -m espalier init .` to initialize"
        ),
        "checks": {
            "presence": {
                "required": committed_required,
                "surface_present": not committed_missing,
                "surface_missing": bool(committed_missing),
                "present_paths": committed_present,
                "missing_paths": committed_missing,
                "partial": bool(committed_missing) and bool(committed_present),
            },
        },
        "next_steps": [
            f"run `{py} -m espalier init .` to generate local runtime artifacts",
        ] if not failures else [
            "restore the missing committed surface from source control",
        ],
        "warnings": warnings,
        "failures": failures,
        "info": [
            "source-checkout mode -- auxiliary runtime files "
            "(.claude/settings.json, reports/*.json, .espalier/integrity.json) "
            f"are generated by `{py} -m espalier init` and not required here",
        ],
        "doc_drift": [],
    }


# A grounded repo has a populated docs/CONVENTIONS.md (self-host ~1.7k lines).
# Fusion RESEED-empties it and a LEGACY in-place `init` shipped none, so both
# fell below this floor. Since 2026-08-01 `init` seeds a Tier-3 stub
# (`espalier/assets/seed/CONVENTIONS.md`) that carries MORE content lines than
# this floor -- 22 prompt-prose lines on 2026-09-05 -- so line-counting alone
# read every fresh install as grounded and the `/analyze` nudge never fired
# (DEF-687). The seed stamp is the durable signal: an UNTOUCHED seed is
# ungrounded whatever its length; the floor still covers unstamped / edited
# copies. Heuristic threshold -- a review knob.
_GROUNDING_MIN_CONTENT_LINES = 15


def _needs_grounding(repo_root: Path) -> bool:
    """True when docs/CONVENTIONS.md is absent, still the untouched seeded
    stub, or near-empty -- the signal that first-run grounding (``/analyze``)
    has not been run yet.

    A grounded repo does not trip this, so healthy repos are never nagged.
    An unreadable file returns False (a read error is not 'ungrounded').
    """
    conv = repo_root / "docs" / "CONVENTIONS.md"
    if not conv.is_file():
        return True
    try:
        text = conv.read_text(encoding="utf-8")
    # UnicodeDecodeError is a ValueError, NOT an OSError, so it escaped this
    # handler entirely. docs/CONVENTIONS.md is adopter-OWNED — a Windows adopter
    # can resave it as cp1252 — and the escape crashed `doctor`, the command
    # whose job is to report on a broken repo. Same fallback: a read error is
    # not "ungrounded".
    except (OSError, UnicodeDecodeError):
        return False
    # The seeded stub, byte-for-byte as `init` wrote it: nobody has grounded
    # this repo yet, however many prompt lines the stub carries. An operator
    # edit (hash mismatch) or an unstamped copy falls through to the floor.
    if seed_is_untouched(text):
        return True
    content_lines = [
        ln for ln in text.splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    return len(content_lines) < _GROUNDING_MIN_CONTENT_LINES


def run_doctor_check(
    repo_root: Path,
    *,
    config_path: Path | None = None,
    skip_self_host: bool = False,
    check_doc_drift: bool = False,
    mode: str | None = None,
) -> dict[str, Any]:
    """Run health checks and classify the repo as pass / warn / fail.

    Special-case: fresh, never-initialized repos return status='uninitialized'
    with a friendly next-step pointer rather than a 'failures' wall — README
    markets `doctor` as a no-init-required first step.

    ``mode`` either auto-detects the repo mode (``source_checkout``,
    ``initialized_self_host``, etc.) or accepts an explicit caller override.
    Source-checkout mode skips checks that depend on gitignored runtime
    artifacts (``.claude/settings.json``, ``reports/*.json``,
    ``.espalier/integrity.json``) so CI invocations on a fresh clone don't
    spuriously fail before init has run. The detected mode is included in
    the report dict.
    """
    repo_root = repo_root.resolve()

    # Before any presence or mode question: a `.claude` this process cannot
    # search or list gets ONE failure naming the permission. Asked later, the
    # same tree read as every deployed file missing plus "run init" on
    # CPython 3.14, and as a PermissionError out of the first `exists()` on
    # 3.10-3.13 (DEF-763, driven on real 3.10, 3.13 and 3.14 2026-09-13).
    unreadable = surface_contract.unreadable_harness_root(repo_root)
    if unreadable is not None:
        return _unreadable_report(repo_root, unreadable)

    presence = _surface_presence(repo_root)
    detected_mode = mode or _detect_repo_mode(repo_root)

    # Uninitialized branch: gentle first-run guidance, not a JSON failure dump.
    if detected_mode == REPO_MODE_UNINITIALIZED:
        return _uninitialized_report(repo_root, detected_mode)

    # Source-checkout branch: committed surface present but no runtime
    # artifacts yet. Skip the auxiliary-required-paths check (those are
    # generated by init) and the self-host gate (which inspects them).
    # Reports cleanly so CI invocations on a fresh clone exit 0.
    if detected_mode == REPO_MODE_SOURCE_CHECKOUT:
        return _source_checkout_report(repo_root, detected_mode, presence)

    plan = _load_plan(repo_root)

    # Uninstalled branch (DEF-770): the saved plan and the runtime markers
    # survive `clean-generated --execute`, so the tree still detects as an
    # initialized consumer repo and fell through to the saved-plan branch
    # below. When nothing the harness deploys remains and settings.json
    # wires no Espalier hook, the tree is uninstalled and is reported the
    # way a never-initialized one is, naming the runtime state still here.
    # Not gated on the plan being present: the adopter who then deletes
    # that state (the plan file with it) keeps their unwired settings.json,
    # which is a runtime marker, so the tree still detects as initialized
    # -- and with nothing left to name, it IS the never-initialized report.
    if (
        detected_mode == REPO_MODE_INITIALIZED_CONSUMER
        and not _deployed_surface_remains(repo_root, plan)
    ):
        leftovers = _uninstall_leftovers(repo_root)
        if leftovers:
            return _uninstalled_report(repo_root, detected_mode, leftovers)
        return _uninitialized_report(repo_root, detected_mode)

    unreadable = [
        p for p in AUXILIARY_REQUIRED_PATHS
        if p.endswith(".json")
        and (repo_root / p).exists()
        and not report_is_json_object(repo_root / p)
    ]

    has_surface = not presence["surface_missing"]
    audit = run_cc_surface_gate(repo_root) if has_surface else {"status": "skipped"}
    reflect = reflect_repo(repo_root) if has_surface else {}
    recover = assess_repo_state(repo_root) if has_surface else {"status": "skipped"}
    diff = diff_repo(repo_root, config_path) if has_surface else {
        "fingerprint_changed": False, "build_plan_changed": False,
    }
    # The surface gate wraps the same run_cc_surface_gate the audit above
    # stands down on a tree with a missing surface. On that tree the presence
    # failure names the paths; a second line for the same fact read
    # `self-host surface gate: fail` to an adopter with no self-host gate to
    # fail, and the stderr one-liner counted two errors for one (DEF-785,
    # driven 2026-09-12 on a consumer tree missing one cc/ doc).
    self_host = (
        run_self_host_check(repo_root) if not skip_self_host and has_surface
        else {"status": "skipped", "surface_gate_status": "skipped"}
    )

    # C (CV2 F4): doctor never consulted the integrity manifest, so a present-but-
    # neutered governance hook (e.g. write_guard.py truncated to empty) read as
    # "safe to proceed" while `espalier integrity verify` reported drift. Fold the
    # check into the wall. Guard against a crash (fail-honest, never fail-loud) AND
    # against a false-RED on an ABSENT manifest (never-refreshed repo) — the
    # MANIFEST_ABSENT sentinel is not edit-drift (matches cmd_integrity).
    # ONLY absent is exempt. A manifest that is present but unusable (corrupt,
    # non-dict, symlinked) returns MANIFEST_UNREADABLE and is reported: it used
    # to share the absent sentinel, so doctor said status=warn / exit 0 /
    # failures=[] on a repo whose tamper-detection was blind.
    integrity_drift: list[str] = []
    integrity_unreadable = False
    if has_surface:
        try:
            _integ = load_integrity_module()
            _ok, _mismatched = _integ.verify_integrity(repo_root)
            if not _ok and _mismatched != [_integ.MANIFEST_ABSENT]:
                integrity_drift = _mismatched
                # Classified HERE, where the module is in scope — the reporting
                # block below runs even when this branch was skipped entirely.
                integrity_unreadable = _mismatched == [_integ.MANIFEST_UNREADABLE]
        except (OSError, AttributeError):
            # FileNotFoundError is an OSError, so the old (OSError,
            # FileNotFoundError) tuple was redundant. AttributeError is the
            # addition and it is load-bearing: this block reads NAMES off a
            # module loaded by file path, so a version-skewed or neutered
            # _integrity.py (the pack's own motivating scenario, applied to the
            # verifier itself) raised out of a block whose whole contract is
            # "no integrity signal, not a crash" -- in a command CI invokes.
            pass  # bridge/manifest unavailable -> no integrity signal, not a crash

    ownership_delta = _three_way_ownership(repo_root, plan)

    failures: list[str] = []
    warnings: list[str] = []
    info: list[str] = []
    next_steps: list[str] = []

    # Lazy import (cli imports doctor at module top -- a top-level back-import
    # would be circular). The subprocess-spawning _remedy_py() (the resolver behind it) is
    # CALLED only inside the failure branches below, the fingerprint-drift
    # WARNING branch, and the unstamped-seed INFO line (which fires only on an
    # ADOPTER tree where a seed doc has lost its first-line stamp -- never on an
    # untouched tree, and never on self-host, whose docs are the seed sources
    # and carry no stamp at all) -- never on the fully-healthy path, which is
    # the property worth preserving.
    # (It said "only inside the failure branches"; the drift next-step made
    # that false, so it was narrowed rather than left contradicting the code
    # three hundred lines down; the info line widened it once more, and this
    # sentence moved with it -- a code-reviewer caught the stale version. The
    # DEF-715 allow-gap INFO line widened it again: it spells the merge command
    # only when the file lacks a profile rule, which is a stale install, not
    # the healthy path.)

    if presence["surface_missing"]:
        failures.append(
            f"missing required managed surface: {presence['missing_paths']}"
        )
        next_steps.append(f"run `{_remedy_py()} -m espalier init <repo>` to initialize the harness")
    if unreadable:
        # Names the paths, and says "managed JSON file" rather than "report":
        # `.claude/settings.json` is a member of this set and is not a report,
        # so the old headline sent a settings.json victim looking in reports/.
        failures.append(
            f"{plural(len(unreadable), 'required managed JSON file')} unreadable: "
            + ", ".join(unreadable)
        )
        # The remedy is NOT single-valued, which is why this branch splits its
        # advice by WHICH file is unreadable. Driven 2026-08-26 against all three
        # members of AUXILIARY_REQUIRED_PATHS: `fingerprint` rewrites the two
        # under reports/ and clears the failure for both; it does not touch
        # .claude/settings.json at all. And `init` does NOT repair a corrupt
        # settings.json -- it treats a present file as operator-edited, preserves
        # it, and writes settings.json.new beside it -- so the file has to be
        # moved aside first. Each line is emitted only for the file it applies
        # to; the operator should never have to evaluate the conditional.
        stale_reports = [p for p in unreadable if p.startswith("reports/")]
        if stale_reports:
            _append_step(
                next_steps,
                f"run `{_remedy_py()} -m espalier fingerprint .` to "
                f"rewrite {', '.join(stale_reports)} from the live tree"
            )
        if ".claude/settings.json" in unreadable:
            settings_json = repo_root / ".claude" / "settings.json"
            if surface_contract.is_effectively_empty_file(settings_json):
                # No content to preserve, so no move-aside: init rewrites an
                # empty file in place (DEF-700, second leg).
                _append_step(
                    next_steps,
                    f"run `{_remedy_py()} -m espalier init .` -- "
                    ".claude/settings.json is empty, and init rewrites an "
                    "empty file in place"
                )
            else:
                _append_step(
                    next_steps,
                    "move .claude/settings.json aside (or delete it), then run "
                    f"`{_remedy_py()} -m espalier init .` to redeploy it "
                    "-- init preserves a present-but-corrupt settings.json and only "
                    "writes settings.json.new beside it"
                )
    if integrity_unreadable:
        # NOT drift: the manifest is present and unusable, so nothing was
        # compared at all. Saying "1 protected file changed out of band" would
        # send the operator hunting for an edit that never happened, and the
        # `integrity verify` next-step would just repeat this same verdict.
        failures.append(
            "integrity manifest present but unreadable (.espalier/integrity.json) "
            "-- tamper detection is not running"
        )
        from espalier.cli import _maintenance_mode_invocation
        next_steps.append(
            "inspect .espalier/integrity.json, then rebuild it by running, "
            "in your own terminal:\n"
            + _maintenance_mode_invocation(
                f"{_remedy_py()} -m espalier integrity refresh .")
        )
    elif integrity_drift:
        failures.append(
            f"integrity drift: {plural(len(integrity_drift), 'protected file')} changed out of band"
        )
        next_steps.append(
            f"run `{_remedy_py()} -m espalier integrity verify .` to see which protected files drifted"
        )
    if audit.get("status") == "fail":
        # The finding, not only the verdict: the gate's first error is what
        # the adopter acts on, and the headline (`primary_reason` is the
        # first failure) used to be the nameless verdict (DEF-785).
        audit_detail = first_error_detail(audit)
        failures.append(
            "audit (surface gate) did not pass"
            + (f": {audit_detail}" if audit_detail else "")
        )
        # Diagnostic first, then a conditional repair. Driven: `audit` is
        # read-only and leaves the failure exactly where it was, so offering it
        # alone would be an action that fixes nothing; `init` DOES clear the
        # common shape (a file cc/PACK_MANIFEST.txt promises that is no longer
        # on disk). Both halves are stated because the gate has other arms that
        # `init` does not repair.
        _append_step(
            next_steps,
            f"run `{_remedy_py()} -m espalier audit .` to see which "
            "surface check failed -- it only reports; if the finding names files "
            "cc/PACK_MANIFEST.txt promises but disk no longer has, "
            f"`{_remedy_py()} -m espalier init .` restores them"
        )
    if recover.get("status") == "fail":
        # The recovery assessor is a different oracle from the surface gate,
        # and on the common shape -- one managed file gone -- the two see ONE
        # fact: the audit line above already reads `PACK_MANIFEST promises
        # missing files: [...]`, and this branch used to add `recovery check
        # reported blocking conditions` beside it, naming neither the file
        # nor what "blocking" meant, so the stderr one-liner counted two
        # errors for one (DEF-786, driven 2026-09-12 with smoke.md deleted
        # on a fresh init tree). So: the line names the paths the assessor
        # found, and when every one of them is already in a failure above,
        # the line is withheld -- the recommendations are still forwarded.
        recover_paths = [
            p for key in ("missing", "plan_missing_docs", "manifest_missing_docs")
            for p in (recover.get(key) or [])
            if isinstance(p, str)
        ]
        # Named = present as a whole path token in a failure above, never as
        # a substring: `commands/smoke.md` is inside
        # `.claude/commands/smoke.md`, and a substring test withheld a path
        # the audit had not named (driven in review).
        already_named = " ".join(failures)

        def _named(path: str) -> bool:
            return re.search(
                rf"(?<![\w./-]){re.escape(path)}(?![\w./-])", already_named
            ) is not None

        clauses: list[str] = []
        if recover_paths and not all(_named(p) for p in recover_paths):
            counts = ", ".join(
                f"{len(recover.get(key) or [])} {label}"
                for key, label in (
                    ("missing", "required paths missing"),
                    ("plan_missing_docs", "promised docs missing"),
                    ("manifest_missing_docs", "manifest entries missing"),
                )
                if recover.get(key)
            )
            clauses.append(f"{counts}: {recover_paths}")
        # Only the PATH clause can be withheld; a path-less reason is a fact
        # the audit line never carries and is always said.
        unreadable = [
            p for p in (recover.get("unreadable_reports") or []) if isinstance(p, str)
        ]
        if unreadable:
            clauses.append(f"{len(unreadable)} report(s) unreadable or malformed: {unreadable}")
        # The gate status the assessor read is the report `run_cc_surface_gate`
        # wrote a moment ago: when the audit line above already says the gate
        # did not pass, this clause is that fact a second time and is withheld
        # with the paths; when the audit passed, the assessor is reading a
        # stale or foreign report and the clause is the only reporter of it.
        gate = str(recover.get("surface_gate_status") or "")
        if gate and gate.lower() != "pass" and audit.get("status") != "fail":
            clauses.append(f"surface gate status {gate}")
        if clauses:
            failures.append("recovery check: " + "; ".join(clauses))
        elif not recover_paths:
            reasons = [r for r in (recover.get("fail_reasons") or []) if isinstance(r, str)]
            failures.append(
                "recovery check: " + ("; ".join(reasons) if reasons else "reported a failure it did not name")
            )
        # Forward the recovery details so the operator gets actionable next
        # steps without having to re-run `espalier recover .` separately —
        # otherwise doctor drops the recommendations from `assess_repo_state`.
        # Dedup case-insensitively so "Run `espalier init`" and "run
        # `espalier init`" don't both land in next_steps.
        existing_lc = {s.lower() for s in next_steps}
        for rec in recover.get("recommendations", []):
            if rec and rec.lower() not in existing_lc:
                next_steps.append(rec)
                existing_lc.add(rec.lower())
    # Shared accept-set (espalier.self_hosting) rather than a third local one:
    # this copy omitted `uninitialized` and `skipped_release_export`, so a tree
    # the CLI reports rc=0 for was a doctor failure. A real failure now names
    # its own reason instead of "did not pass".
    # On an initialized tree the self-host check wraps the SAME gate the
    # audit above ran, so when the audit failed its line already says so
    # with the finding; a second line for the same gate read as a second
    # error (driven 2026-09-12: one deleted command file, three errors,
    # DEF-785's sister site). The check's own verdict stays in the report
    # block below; only the duplicate failure line is withheld.
    self_host_failure = gate_failure_reason(self_host)
    if self_host_failure and audit.get("status") != "fail":
        failures.append(self_host_failure)

    # Deleted-governance-event completeness oracle.
    wiring_failures = _check_governance_event_wiring(repo_root)
    settings_path = repo_root / ".claude" / "settings.json"
    # DEF-715: a profile allow rule added after this install never reaches the
    # operator's settings.json (the merge preserves permissions by contract),
    # and nothing said so. Name the rules the file lacks. Info, never a
    # failure -- permissions are theirs -- and read-only; the interpreter probe
    # in the hint runs only when there is a gap, never on the healthy path.
    if os.path.isfile(settings_path):
        from espalier.cli import (  # lazy: cli imports doctor at top level
            installed_settings_profile,
            settings_allow_gaps,
        )
        profile = installed_settings_profile(repo_root)
        gaps = settings_allow_gaps(settings_path, profile=profile, repo_root=repo_root)
        if gaps is not None and gaps[0]:
            lacking = gaps[0]
            shown = ", ".join(lacking[:3]) + (f", +{len(lacking) - 3} more" if len(lacking) > 3 else "")
            info.append(
                f".claude/settings.json lacks {plural(len(lacking), 'allow rule')} of the "
                f"{profile!r} profile ({shown}); "
                f"`{_remedy_py()} -m espalier merge-settings . --profile {profile} --add-allows` "
                f"appends what is missing and never removes yours"
            )
        elif gaps is not None and gaps[1]:
            info.append(
                f".claude/settings.json: {gaps[1]}; the {profile!r} profile's allow "
                "rules could not be compared (merge-settings says the same)"
            )
        # DEF-508: the statusLine fallback is host-keyed at render time and the
        # file can outlive or leave that host; say which direction it disagrees.
        info.extend(_statusline_fallback_notes(settings_path, repo_root))
    if wiring_failures and _is_benign_hookless_settings(settings_path):
        # "Consolidate, keep fail-closed": a readable+valid settings.json that
        # wires zero Espalier hooks (no hooks key, or a hooks dict referencing
        # no canonical tools/cc/hooks/ path) is the brought-your-own onboarding
        # case (init leaves it untouched). Collapse
        # the N near-identical per-gate failures into ONE fail-closed line that
        # STILL names every deployed gate + points at merge-settings, and surface
        # the remedy as a next-step — stopping the wall-of-red that contradicts the
        # honest exit-0 init banner WITHOUT weakening the deny path (status stays
        # fail; every gate named). Consolidation is presentation-only: the oracle
        # above stays per-gate so it remains count-parity-locked with ci_guard.
        from espalier import harness_config
        hooks_dir = repo_root / "tools" / "cc" / "hooks"
        unwired = [
            s for s in sorted(harness_config.GOVERNANCE_BLOCKING_HOOKS)
            if (hooks_dir / s).is_file()
        ]
        failures.append(_consolidated_unwired_line(unwired))
        _refused = _merge_would_be_refused(repo_root)
        if _refused:
            _append_step(
                next_steps,
                _merge_refusal_step(_refused, _remedy_py()),
            )
        else:
            next_steps.append(
                f"run `{_remedy_py()} -m espalier merge-settings` to wire the governance hooks"
            )
    else:
        # Partial disarm / unprovable / tampered settings stays loud (the per-gate
        # wall is the genuine tamper signal — it must not be softened).
        failures.extend(wiring_failures)
        # ...but loud is not the same as actionable. `_primary_reason` surfaces
        # failures[0], so on this branch the HEADLINE verdict used to arrive with
        # next_steps == [] — the single most alarming thing doctor says, paired
        # with nothing. The remedy is SHAPE-dependent and only one shape has a
        # command: driven 2026-08-27, `merge-settings` tops up a deleted event
        # and restores the gate, and does nothing at all for an inert one.
        # Naming it for both would send half these operators to a command that
        # reports success and leaves them disarmed.
        from espalier import harness_config as _hc
        # The bucketing is SHARED with `cli._disarmed_diagnosis` (one home in
        # harness_config; its callers are the narrators) -- the two surfaces narrate the same
        # tree, so a second inline copy of it here would be a sister_site_probe
        # clique whose only product is the chance for the two to drift apart.
        # What stays local is the POLICY: this arm reports legacy_form below,
        # while the enforcement claim abstains on it.
        shapes = _hc.group_unwired_gates_by_shape(repo_root)
        unrecognized = sorted(
            script
            for shape, scripts in shapes.items()
            if shape not in _hc.GATE_SHAPES
            for script in scripts
        )
        voided = shapes.get(_hc.GATE_VOIDED_SETTINGS, [])
        if voided:
            # First, and it displaces the per-gate advice rather than joining
            # it: on a voided file every gate reads dead no matter how it is
            # wired, so "re-wire <script>" is work that changes nothing. The
            # entry that killed them is frequently NOT one espalier manages.
            _voided_detail = surface_contract.hooks_config_voided_by(
                surface_contract._load_settings_hooks_cfg(repo_root)
            )
            next_steps.append(
                "fix "
                + (_voided_detail or "the malformed hook entry")
                + " in .claude/settings.json -- Claude Code validates the whole "
                "hooks block and discards ALL of it if any group or entry is "
                "malformed, warning about nothing, so "
                + ", ".join(voided)
                + " cannot fire whatever their own wiring says. Other wiring "
                "problems on this tree are masked until it is fixed; re-run "
                "doctor afterwards"
            )
        if shapes.get(_hc.GATE_ABSENT):
            # ⚠ The caveat is the SAME one `cli._unwired_gate_diagnosis` carries,
            # and it was missing here while the two surfaces shared a bucketing
            # introduced to keep them aligned. An operator who runs this command
            # and sees success does not come back for the steps below it, so a
            # remedy list whose first line looks total is a false finish.
            # ⚠ DERIVED, not hand-unioned (STANDING_PRINCIPLES §14) -- the twin
            # of cli's, and it was the twin of cli's OMISSION too: a shape added
            # later dropped out of the caveat on both surfaces at once with
            # nothing red. GATE_ABSENT is the only shape the PLAIN merge repairs.
            unfixed = sorted(
                script
                for shape, scripts in shapes.items()
                if shape != _hc.GATE_ABSENT
                for script in scripts
            )
            refused = _merge_would_be_refused(repo_root)
            if refused:
                _append_step(
                    next_steps,
                    _merge_refusal_step(refused, _remedy_py()),
                )
            else:
                next_steps.append(
                    f"run `{_remedy_py()} -m espalier merge-settings` to "
                    "wire the governance events missing from .claude/settings.json"
                    + (f" -- this does NOT fix {', '.join(unfixed)}" if unfixed
                       else "")
                )
        # Two shapes, two sentences. They share a remedy (a hand edit) and NOT
        # a diagnosis: an inert gate is wired and does nothing, an orphaned one
        # is not wired at all. Telling an operator their missing entry "runs no
        # interpreter" sends them looking for a command that is not there.
        # The value init WRITES, for the sentences that tell the operator what
        # to put in settings.json by hand (DEF-758). Kept in its own f-string,
        # apart from the command it follows: the AST pin reads an f-string that
        # carries `-m espalier` and this name as a remedy spelled with it.
        written = _resolver_hint()
        inert = shapes.get(_hc.GATE_INERT, [])
        if inert:
            next_steps.append(
                f"run `{_remedy_py()} -m espalier merge-settings . "
                "--repair`: "
                + ", ".join(inert)
                + (" is" if len(inert) == 1 else " are")
                + " wired but the entry runs no interpreter; --repair rewrites "
                "espalier's own entry to canonical (backup first), or set the "
                + f"command back to `{written}` with the script path in args by hand"
            )
        orphaned = shapes.get(_hc.GATE_ORPHANED, [])
        if orphaned:
            next_steps.append(
                "edit .claude/settings.json by hand: "
                + ", ".join(orphaned)
                + (" has" if len(orphaned) == 1 else " have")
                + " no entry under "
                + ", ".join(sorted({_hc.GATE_EVENT_OF(s) for s in orphaned}))
                + " -- plain merge-settings will NOT add it because that event "
                f"key already exists; `{_remedy_py()} -m espalier "
                "merge-settings . --repair` adds the entry (backup first), or "
                + f"add it yourself (command: `{written}`, script path in args)"
            )
        miswired = shapes.get(_hc.GATE_MISWIRED, [])
        if miswired:
            # Verifiably dead, unlike legacy_form -- the extractor read the
            # entry. Name which half is wrong per gate; `--repair` puts the
            # entry back under its canonical event with its canonical matcher.
            next_steps.append(
                "edit .claude/settings.json by hand: "
                + "; ".join(
                    f"{script} is {_hc.miswiring_detail(repo_root, script)}"
                    for script in miswired
                )
                + f" -- `{_remedy_py()} -m espalier merge-settings . "
                "--repair` puts espalier's own entry back under its canonical "
                "event with its canonical matcher (backup first), or move or "
                "widen it by hand"
            )
        # The leftover arm -- same class as cli's, fixed on both surfaces
        # because "class-fix scope = every shipped surface" (STANDING_PRINCIPLES
        # §8). Here the gate is at least still NAMED by the per-gate failures
        # above, so an unknown shape costs the ACTION rather than the finding --
        # which is DEF-433 (a verdict paired with nothing to do), not silence.
        if unrecognized:
            next_steps.append(
                "inspect .claude/settings.json by hand for "
                + ", ".join(unrecognized)
                + " -- the wiring is not executable and does not match any "
                "shape this check can name, so no automatic remedy applies"
            )
        legacy = shapes.get(_hc.GATE_LEGACY_FORM, [])
        if legacy:
            next_steps.append(
                f"run `{_remedy_py()} -m espalier merge-settings . "
                "--repair` to re-wire " + ", ".join(legacy) + " in exec form "
                "(backup first), or do it by hand (command: "
                + f"`{written}`, script path in args) -- the "
                "pre-v0.6.5 shell form cannot be verified"
            )

    # A value-marker kill-switch in the LIVE settings (disableAllHooks: true /
    # permissions.defaultMode == bypassPermissions) silences EVERY governance
    # gate at runtime, yet the wiring oracle above reads a fully-wired repo as
    # green. Consult the shared C-3 live-kill-switch check (both settings.json
    # and settings.local.json) so doctor can never report "safe to proceed"
    # while all enforcement is off. This is the GLOBAL instance of the
    # present-but-neutered gate class the integrity bridge hardens per-file.
    from espalier.selfcheck import check_live_kill_switch_absent
    kill_switch = check_live_kill_switch_absent(repo_root)
    if not kill_switch.passed:
        failures.append(
            "governance kill-switch active in live settings: "
            + "; ".join(kill_switch.failures)
        )
        next_steps.append(
            "remove disableAllHooks / bypassPermissions from .claude/settings.json "
            "to re-enable the governance hooks"
        )

    # DEF-433: EVERY warn branch below pairs its warning with a next_step. A
    # `warn` verdict that hands back an empty action list tells the operator
    # something is wrong and nothing to do about it. Only the drift branch used
    # to do this; the rest are paired here.
    # `tests/test_doctor.py::TestEveryWarningCarriesANextStep` drives each
    # branch and reds on an unpaired one, and its count ratchet reds when a NEW
    # warn site appears without a fixture.
    #
    # ⚠ SCOPE, because the earlier wording here claimed completeness it did not
    # have. That ratchet sees `warnings.append` / `warnings.extend` inside this
    # function and NOTHING ELSE. Driven 2026-08-26: an injected `warnings += [..]`
    # (an AugAssign, not a Call) passes it, and so does an injected
    # `failures.append(...)`. The failure branches are the larger population —
    # 11 sites against 9 — and the worse one, since `_primary_reason` surfaces
    # `failures[0]`, so an unpaired failure is the headline verdict with an empty
    # action list. Their pairing is enforced by nothing yet.
    if ownership_delta["stale_saved_paths"]:
        warnings.append(
            f"stale saved-plan paths no longer on disk: {ownership_delta['stale_saved_paths']}"
        )
        next_steps.append(
            f"run `{_remedy_py()} -m espalier init .` to redeploy the "
            "managed files the saved plan still lists -- or "
            f"`{_remedy_py()} -m espalier fingerprint .` to re-baseline "
            "the plan if you removed them on purpose"
        )
    if ownership_delta["missing_from_saved_plan"]:
        warnings.append(
            f"on-disk managed paths missing from saved plan: {ownership_delta['missing_from_saved_plan']}"
        )
        next_steps.append(
            f"run `{_remedy_py()} -m espalier fingerprint .` to "
            "re-baseline the saved plan against the managed files now on disk"
        )
    if ownership_delta.get("unshipped_saved_agents"):
        # Information, not drift (DEF-756): the plan recommends them, nothing
        # ships them, and no command puts them on disk.
        info.append(
            "recommended agents with no packaged body, so none is deployed "
            f"(the saved plan lists them): {ownership_delta['unshipped_saved_agents']}"
        )
    if reflect.get("broken_markdown_links") or reflect.get("plan_missing_docs"):
        warnings.append("reflection found surface drift")
        next_steps.append(
            f"run `{_remedy_py()} -m espalier reflect .` to list the "
            "broken links and missing docs behind that drift"
        )
    if diff.get("fingerprint_changed") or diff.get("build_plan_changed"):
        warnings.append("saved reports differ from fresh inference")
        _append_step(
            next_steps,
            f"run `{_remedy_py()} -m espalier fingerprint .` to "
            "re-baseline the saved reports against the live tree"
        )
    if presence["partial"]:
        warnings.append("only part of the generated surface is present")
        next_steps.append(
            f"run `{_remedy_py()} -m espalier init .` to finish "
            "deploying the generated surface (it preserves files you have edited)"
        )

    doc_drift: list[str] = []
    if check_doc_drift:
        doc_drift = _check_doc_drift(repo_root)
        if doc_drift:
            warnings.append(
                f"doc-drift findings: {len(doc_drift)} (run with --check-doc-drift for details)"
            )
            next_steps.append(
                f"read the {plural(len(doc_drift), 'doc-drift finding')} under "
                "`doc_drift` in this report and bring each document back in line "
                "with the code it describes"
            )

    # DEF-551: the required-.gitignore question, asked by a READ-ONLY command.
    # Until now only the mutating init/upgrade path ever raised it, so an
    # adopter who dismissed init's WARN had nothing that would mention it
    # again. Same computation `_handle_gitignore` renders from, so the two
    # cannot disagree about the facts.
    #
    # `withheld` entries are EXCLUDED from the advice on purpose: those are
    # paths git already tracks, and telling the operator to ignore one would
    # strand it in the tracked-and-ignored state that DEF-11 exists to avoid.
    # They are reported as context, never as an action.
    from espalier.cli import gitignore_status  # lazy: cli imports doctor at top level

    gi_status = gitignore_status(repo_root)
    gi_actionable = [e for e in gi_status.missing if e not in gi_status.withheld]
    if gi_actionable:
        warnings.append(
            "required .gitignore entries missing: "
            + ", ".join(gi_actionable)
            + ("" if gi_status.exists else " (no .gitignore in this repo)")
        )
        next_steps.append(
            f"run `{_remedy_py()} -m espalier init .` again to append the missing "
            f".gitignore {plural(len(gi_actionable), 'entry', 'entries')} "
            f"({', '.join(gi_actionable)}) as a block (a re-init is safe), so the "
            "harness's machine-specific runtime state stays uncommitted"
        )
    if gi_status.withheld:
        info.append(
            "required .gitignore entries withheld because git already tracks "
            "the path: " + ", ".join(sorted(gi_status.withheld))
        )
    if gi_actionable and gi_status.oracle != "git":
        # DEF-635: the spelling compare reads a broader pattern that already
        # covers an entry as absent. Say which oracle answered rather than let
        # a weaker verdict wear the stronger one's certainty.
        info.append(
            "the .gitignore check matched spellings line-for-line because git "
            "could not answer; a broader pattern that already covers an entry "
            "(`*.py[cod]` for `*.pyc`) is reported missing under that check"
        )

    python_resolver_issues = _check_python_resolver(repo_root)
    warnings.extend(python_resolver_issues)
    if python_resolver_issues:
        # DEF-620: this used to say plain `init .`, which does NOT overwrite an
        # existing settings.json (user sovereignty) -- measured before and
        # after, `group_unwired_gates_by_shape` returned the identical
        # `{'legacy_form': [...]}` both times. The adopter could follow the step
        # forever. `--rewire-interpreter` is the opt-in that actually rewrites.
        #
        # DEF-727: and it was spelled with `_detect_python_command()`, the
        # resolver whose answer the warning above had just called broken -- on
        # the Windows walk 2 host, `python -m espalier ...` with a Python 2
        # `python`. `_remedy_hint` spells a name that clears the floor (the one
        # running this command when PATH offers none) and says whether the
        # rewire would even find a target. When it would not, the blocker is
        # PATH, not a missing install: this command is running under a Python
        # that clears the floor, so "install Python" prescribed an install the
        # operator had already done (driven by the code review).
        hint, resolver_clears_floor, probed = _remedy_hint()
        step = (
            f"run `{hint} -m espalier init . "
            "--rewire-interpreter` to rewire the hook commands to an "
            "interpreter that resolves on this host and meets Python "
            f"{floor_text()}+ (changes only the interpreter name; keeps a .bak of the file)"
        )
        if not resolver_clears_floor:
            step = (
                f"put a Python {floor_text()}+ on PATH as {probed} first -- "
                f"neither name answers as one now, so the rewire has no target "
                "to write -- then " + step
            )
        next_steps.append(step)

    # Surface missing load-bearing external tools (ruff, future
    # gitleaks/codespell/etc.) so the lint-gate-as-regression-test
    # doesn't silently degrade when the binary isn't installed.
    #
    # ruff is a load-bearing gate only on the self-host repo: its ruff-lint CI
    # job is `if: is_source == 'true'`, and ruff ships only in espalier's own
    # dev extras. A median `pip install` adopter has no linter and no ruff gate,
    # so a missing-ruff warning must not degrade THEIR headline status. Gate on
    # self-host, matching the harness-specific checks above.
    #
    # NOTE: this gate is WHOLE-LOOP — every tool in the registry is treated as
    # self-host-only. That is correct only while the registry holds solely
    # self-host-only tools (ruff today). A tool adopters MUST be warned about
    # (e.g. a secret scanner like gitleaks) needs per-tool adopter-relevance
    # gating added first; a new registry row ALONE would be silently suppressed
    # for adopters here (and by the same-shape gate in session_start.py).
    if surface_contract.is_self_host_repo(repo_root):
        for tool_name, install_hint in _LOAD_BEARING_EXTERNAL_TOOLS.items():
            tool_warnings = _check_external_tool(tool_name, install_hint)
            warnings.extend(tool_warnings)
            if tool_warnings:
                next_steps.append(
                    f"install the missing load-bearing tool {tool_name!r}: {install_hint}"
                )

    # A seed doc whose first-line stamp is gone is the adopter's doc as far as
    # the fingerprint is concerned, and the day-one noise (`Large files
    # detected`, `docs_heavy`) comes back with nothing naming the cause. Say it
    # here, where the adopter already looks (DEF-691), and print the stamp
    # itself (DEF-696). Self-host is gated exactly as `_check_doc_drift` is:
    # the docs HERE are the seed sources and never carried a stamp (driven: 20
    # of 20 fired, with a remedy that had no referent). The remedy leads with
    # the one that KEEPS the adopter's edits: the stamp is deterministic --
    # `render_seed_stamp` is `seed_stamp_line` over the same rendered body
    # `init` writes -- so printing it works in every state an adopter can be
    # in: never committed, committed after the tidy, or a legacy pre-stamp
    # deployment. The first cut sent them to `git show HEAD:<file>`, which
    # fails loudly in the first state and returns exit 0 with a plausible
    # wrong line (the adapt header, or the doc's own heading) in the other
    # two. Pasted above an edited body the stamp's digest never matches, so
    # every later `init`/`upgrade` preserves the file by the existing rule
    # (`_seed_redeploy_decision`); above a body that still matches today's
    # packaged bytes (a tidy that removed only the stamp) it restores the
    # untouched status, so the next packaged drift refreshes it again. A legacy
    # copy of an OLDER packaged body is kept from then on but stops receiving
    # packaged updates -- the digest is today's, not that body's -- and
    # delete-then-`init` is that copy's path to current bytes (the first cut
    # claimed the refresh for every legacy copy; the failure-mode pass drove an
    # older body and got `preserve` on drift).
    # Delete-then-`init` re-seeds the packaged body -- for the two grounding
    # docs, the near-empty stub -- and is offered only for a copy the adopter
    # never edited (the second cut offered it unconditionally, and a review
    # pass drove it discarding 61 grounded lines). `upgrade` is not a remedy
    # at all: an unstamped copy is preserved on purpose and a version-current
    # `upgrade` returns before the seed loop. The filenames are the
    # load-bearing tokens, consequence first: the one seed the grounding floor
    # reads, then by size (the large-file symptom); the stamps follow the same
    # three names, and a tree with more unstamped seeds gets the next three on
    # the next run. A seed whose packaged copy this install cannot render is
    # named without a stamp, with the cause, rather than crashing the
    # diagnostic: a package-resource read is a wider family than a filesystem
    # read (`zipfile.BadZipFile` and a zip member's `KeyError` are not
    # `OSError`), so the guard is the broad one `fuse.py`'s rollback uses, and
    # the class name in the text keeps a real bug from hiding as "unreadable".
    if not surface_contract.is_self_host_repo(repo_root):
        from espalier.managed_inventory import (
            get_seed_asset_source,
            render_seed_stamp,
            unstamped_seed_docs,
        )
        unstamped = unstamped_seed_docs(repo_root)
        if unstamped:
            def _consequence(rel: str) -> tuple[int, int]:
                # A stub-backed seed (the canon is `get_seed_asset_source`
                # redirecting it) is the one delete-then-init empties: name it
                # first; then by size, the large-file symptom. A literal
                # `docs/CONVENTIONS.md` here left SHARP_EDGES 19th of 19.
                try:
                    size = (repo_root / rel).stat().st_size
                except OSError:
                    size = 0
                return (0 if get_seed_asset_source(rel) != rel else 1, -size)
            ordered = sorted(unstamped, key=_consequence)
            named = ", ".join(ordered[:3])
            if len(ordered) > 3:
                named += f" (+{len(ordered) - 3} more)"
            verb = "carries" if len(unstamped) == 1 else "carry"
            stamps: list[str] = []
            printed = 0
            for rel in ordered[:3]:
                try:
                    stamp = render_seed_stamp(rel).rstrip("\n")
                except Exception as exc:  # noqa: BLE001 -- a diagnostic must not die on the install it is diagnosing (see the note above)
                    stamps.append(
                        f"{rel}: its packaged copy is unreadable in this install "
                        f"({type(exc).__name__}), so re-install espalier before "
                        "restoring it"
                    )
                    continue
                stamps.append(f"{rel}: `{stamp}`")
                printed += 1
            more = (
                " (once these carry theirs, `doctor` names and stamps the next three)"
                if len(ordered) > 3 else ""
            )
            # The promise is made only for a stamp that was actually printed:
            # an entry that fell into the unreadable branch has no line to
            # paste, and a closing sentence that covered it too was a remedy
            # claim nobody drove (code-review pass, driven on a forged install).
            if printed == 0:
                exact = ""
            else:
                exact = (
                    f" {'Each' if printed > 1 else 'That'} stamp is the exact line "
                    "`init` writes for its file today and needs no git; above an "
                    "edited body its digest never matches, so every later `init` "
                    "and `upgrade` keeps your copy."
                )
            py = _remedy_py()
            info.append(
                f"{plural(len(unstamped), 'seeded doc')} {verb} no "
                f"`espalier:seed-version` first line ({named}) -- that stamp is "
                "what keeps a seed out of your fingerprint, docs surface and "
                "grounding floor. To keep your edits, paste the file's stamp "
                f"back as line 1, above everything else: {'; '.join(stamps)}"
                f"{more}.{exact} Only for a copy you never edited, delete the "
                f"file and re-run `{py} -m espalier init .` to re-seed the "
                "packaged body (for docs/CONVENTIONS.md and docs/SHARP_EDGES.md "
                "that is the near-empty stub: your grounding would be gone). If "
                f"you already re-fingerprinted, re-run `{py} -m espalier "
                "fingerprint .` afterwards"
            )

    # DEF-619: the reporter tier, as warnings -- the governance oracle is
    # pinned to the four gates for parity with ci_guard and left these unseen.
    # LAST, on purpose: `_primary_reason` surfaces warnings[0], and a dead
    # reporter must not outrank a gitignore or doc-drift headline.
    reporter_warnings = _check_reporter_hook_wiring(repo_root)
    warnings.extend(reporter_warnings)
    if reporter_warnings:
        _append_step(
            next_steps,
            f"run `{_remedy_py()} -m espalier doctor .` again after "
            "re-wiring the reporter hooks named in the warnings -- each line "
            "carries its own remedy",
        )

    status = _classify(failures, warnings)
    if status == "pass":
        if _needs_grounding(repo_root):
            next_steps.append(
                "run `/analyze` to ground the harness on this repo "
                "(populate docs/CONVENTIONS.md, distill footguns) -- then proceed"
            )
        next_steps.append("repo is coherent -- safe to proceed with bounded work")

    ownership = ownership_summary(plan, repo_root=repo_root) if (plan or surface_contract.is_self_host_repo(repo_root)) else {
        "mode": "none",
        # Non-self-host fallback only (this branch is unreachable when
        # is_self_host_repo is true), so the base tuple is correct — the
        # "espalier" root that ownership_summary appends for self-host does
        # not belong here.
        "harness_owned_roots": list(HARNESS_OWNED_ROOTS),
        "managed_paths": list(presence["required"]),
        "plan_derived_managed_paths": [],
        "user_owned_by_default": "anything outside the explicit managed-path inventory",
    }

    return {
        "repo_root": str(repo_root),
        "status": status,
        "mode": detected_mode,
        "primary_reason": _primary_reason(failures, warnings, info, next_steps),
        "ran_build": False,
        "checks": {
            "presence": presence,
            "audit": {"status": audit.get("status", "unknown")},
            "reflect": {
                "status": "pass" if not reflect.get("plan_missing_docs") and not reflect.get("broken_markdown_links") else "warn",
                "broken_links": len(reflect.get("broken_markdown_links", [])),
                "missing_docs": len(reflect.get("plan_missing_docs", [])),
            },
            "recover": {"status": recover.get("status", "unknown")},
            "diff": {
                "status": "pass" if not diff.get("fingerprint_changed") and not diff.get("build_plan_changed") else "warn",
                "fingerprint_changed": diff.get("fingerprint_changed", False),
                "build_plan_changed": diff.get("build_plan_changed", False),
            },
            "self_host": {"status": self_host.get("surface_gate_status", "unknown")},
        },
        "ownership": ownership,
        "ownership_delta": ownership_delta,
        "warnings": warnings,
        "failures": failures,
        "info": info,
        "doc_drift": doc_drift,
        "next_steps": next_steps,
    }
