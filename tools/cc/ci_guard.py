#!/usr/bin/env python3
"""CI-tier branch-protection gate (Pack 5 Task 5-C).

This is the only Espalier-Harness enforcement layer with a genuine guarantee —
conditional on the user enabling branch protection in GitHub's UI and
requiring the "verify" status check. That is the JOB name: "Harness Guard" is
the workflow, and GitHub's required-check picker lists check runs (jobs), so
the workflow name is not selectable there.

Behavior:
- Resolve the diff base (BASE_SHA > BEFORE_SHA > merge-base with main).
- Enumerate changed paths via `git diff --name-only <base>..HEAD`.
- If any changed path is in the CI-protected inventory AND the event's one
  marker channel does not carry `HARNESS-UPDATE-APPROVED` -- on a pull
  request the PR title, BOUND to the head under review as
  `HARNESS-UPDATE-APPROVED@<sha>`; on a push the HEAD commit message -- exit
  2 with a human-readable message that names the fragment to add.
- UNCONDITIONAL: if .claude/settings.json or .claude/settings.local.json
  contains a kill-switch finding (disableAllHooks: true,
  permissions.defaultMode: bypassPermissions, empty/no-op hook lists),
  fail merge regardless of the approval marker. Kill-switch settings
  cannot be committed to the public project.
- Otherwise exit 0.

Stdlib-only. Respects the tools/cc/ zero-espalier-import rule by hard-coding
the protected-path inventory here (mirrors surface_contract). Kill-switch
detection is a small local scanner — kept local to honor the strict CI-tier
isolation (no hooks/_integrity.py import either, since CI may run before
that module is in scope).
"""
from __future__ import annotations

import codecs
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def _ci_decode_bom(raw: bytes) -> str:
    """Decode bytes that may carry a UTF-8/16/32 BOM (PowerShell Out-File / editor
    re-encode). Inline mirror of _json_safe.decode_bom / surface_contract.decode_bom
    (zero-imports rule); parity-pinned by tests. UTF-32 is checked before UTF-16 (the
    UTF-32-LE BOM starts with the UTF-16-LE BOM)."""
    if raw[:4] in (codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE):
        return raw.decode("utf-32")
    if raw[:2] in (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig")

APPROVAL_MARKER = "HARNESS-UPDATE-APPROVED"

PROTECTED_FILES: tuple[str, ...] = (
    ".espalier/integrity.json",
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".github/workflows/harness-guard.yml",
    "tools/cc/ci_guard.py",
)

PROTECTED_PREFIXES: tuple[str, ...] = (
    "tools/cc/hooks/",
    # All GitHub Actions workflows fail the merge gate without the
    # HARNESS-UPDATE-APPROVED marker — extends past the harness-guard
    # workflow specifically to cover release.yml, refresh-externals.yml,
    # end-to-end-bench.yml, benchmark.yml.
    ".github/workflows/",
)


def _git(args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=cwd, timeout=30
    )


def _resolve_zero(sha: str) -> str | None:
    if not sha:
        return None
    if set(sha) == {"0"}:
        return None
    return sha


def resolve_base(env: dict[str, str], cwd: str | None = None) -> str:
    """Return the git revision to diff HEAD against."""
    base_sha = _resolve_zero(env.get("BASE_SHA", ""))
    if base_sha:
        return base_sha
    before = _resolve_zero(env.get("BEFORE_SHA", ""))
    if before:
        # Ensure the commit exists locally; fall through to merge-base if not.
        check = _git(["cat-file", "-e", before], cwd=cwd)
        if check.returncode == 0:
            return before
    # Fall back to merge-base with the repo's DEFAULT BRANCH, then the
    # historical (origin/main, main) pair.
    #
    # The default branch is forwarded from the workflow as DEFAULT_BRANCH
    # (github.event.repository.default_branch). It is NOT derived here with
    # `git symbolic-ref refs/remotes/origin/HEAD`: that ref is created by
    # `git clone`, and actions/checkout does `git init` + `remote add` +
    # `fetch`, so the derivation is INERT in the only environment this runs in
    # (driven: `fatal: ref refs/remotes/origin/HEAD is not a symbolic ref`,
    # rc=128).
    #
    # Why this must land BEFORE the workflow's push filter widens: on a
    # `master` adopter a new-branch push sends an all-zeros `before`, both
    # origin/main and main fail, and the last resort diffs against the INITIAL
    # COMMIT -- so every protected path reads as changed, the approval marker
    # becomes required, and the adopter's first branch push exits 2. Widening
    # the trigger without this operand converts silent zero enforcement into
    # loud wrong enforcement on exactly the population it targets.
    default_branch = (env.get("DEFAULT_BRANCH") or "").strip()
    candidates = []
    if default_branch:
        candidates += [f"origin/{default_branch}", default_branch]
    candidates += ["origin/main", "main"]
    seen = set()
    head = _git(["rev-parse", "HEAD"], cwd=cwd).stdout.strip()
    for ref in [r for r in candidates if not (r in seen or seen.add(r))]:
        mb = _git(["merge-base", ref, "HEAD"], cwd=cwd)
        if mb.returncode == 0 and mb.stdout.strip():
            base = mb.stdout.strip()
            # A base EQUAL TO HEAD yields an empty diff, and an empty diff means
            # this gate inspects nothing: a tampered protected path is invisible
            # and the approval marker is never demanded. That is a FAIL-OPEN, and
            # it is reachable without any bad input -- `merge-base X HEAD` is HEAD
            # whenever X is the branch being pushed, i.e. the first push of a repo
            # whose default branch is the one being pushed.
            #
            # PRE-EXISTING, not introduced with the DEFAULT_BRANCH operand:
            # driven against the pre-operand code, the first push of a `main`
            # -default repo already resolved base == HEAD. The operand widens WHICH
            # repos reach it, so it is closed here rather than left for the
            # population this change newly serves.
            #
            # Falling through to the next candidate (ultimately the initial commit)
            # fails CLOSED: every protected path reads as changed and the approval
            # marker is demanded. Loud and wrong beats silent and open for a gate.
            if base != head:
                return base
            print(
                f"ci_guard: WARN: merge-base with {ref!r} is HEAD itself; that "
                f"base would make the diff empty and the gate vacuous. Trying "
                f"the next base candidate.",
                file=sys.stderr,
            )
    # Last resort: diff against the first commit ever.
    first = _git(["rev-list", "--max-parents=0", "HEAD"], cwd=cwd)
    if first.returncode == 0 and first.stdout.strip():
        first_sha = first.stdout.strip().splitlines()[0]
        print(
            "ci_guard: WARN: no base ref found; diffing against initial commit",
            file=sys.stderr,
        )
        return first_sha
    raise RuntimeError("Cannot resolve diff base: no main branch, no initial commit")


def changed_paths(base: str, cwd: str | None = None) -> list[str]:
    result = _git(["diff", "--name-only", f"{base}..HEAD"], cwd=cwd)
    if result.returncode != 0:
        raise RuntimeError(
            f"git diff failed (rc={result.returncode}): {result.stderr.strip()}"
        )
    paths = [
        line.strip().replace("\\", "/")
        for line in result.stdout.splitlines()
        if line.strip()
    ]
    return paths


def is_protected(rel_path: str) -> bool:
    p = rel_path.replace("\\", "/")
    if p in PROTECTED_FILES:
        return True
    for prefix in PROTECTED_PREFIXES:
        if p.startswith(prefix):
            return True
    return False


def head_commit_message(cwd: str | None = None) -> str:
    result = _git(["log", "-1", "--pretty=%B", "HEAD"], cwd=cwd)
    return result.stdout if result.returncode == 0 else ""


# Trigger-aware approval-marker check (BC-032). Routes by GITHUB_EVENT_NAME so
# each trigger only honours the marker source that the trigger cannot tamper with
# (a logical OR over both sources lets a PR author force-push the marker text into
# a new HEAD commit message after a clean review and launder approval):
#
# - PR-like events (pull_request and its privileged twins
#   pull_request_target / merge_group): ONLY env.PR_TITLE, and ONLY a marker
#   BOUND to the head under review -- `HARNESS-UPDATE-APPROVED@<sha>`, where
#   the sha (7 to 40 hex, any case) is a prefix of env.PR_HEAD_SHA, which the
#   deployed workflow forwards from github.event.pull_request.head.sha
#   (DEF-338). The PR title is logged on the PR timeline and force-push does
#   not edit it -- but a title approves the PR, not a commit: with the bare
#   marker, a reviewer approved head A, the author force-pushed head B with a
#   new protected-zone change, and the unchanged title still passed. Naming
#   the head makes the same title go red on the new head until the title is
#   re-bound -- an explicit, timeline-logged act. The binding is
#   self-attested (a PR author can edit their own title), so it is an audit
#   trail that forces a per-head retitle, not independent evidence that a
#   reviewer approved the head; re-review a force-push. A bare marker on a PR
#   event is therefore refused, and a PR event that arrives without a
#   commit-shaped PR_HEAD_SHA fails closed with the remedy named (the script
#   and the workflow deploy together, but install-ci parks a differing
#   workflow as `.new`, so the remedy names that file and the exact line).
# - push events (direct-to-main): ONLY the HEAD commit message, bare or bound
#   -- the message travels with its commit, the pusher already holds write
#   access, and the posture rule below governs the path. PR_TITLE is unset
#   for these events; branch protection gates the direct push itself (out of
#   ci_guard scope).
# - Anything else (workflow_dispatch, repository_dispatch, schedule,
#   empty / unknown event): REFUSE the marker. These triggers have no
#   review context, so the marker on them would be unconditionally
#   laundered.
_PR_EVENTS: frozenset[str] = frozenset({
    "pull_request",
    "pull_request_target",
    "merge_group",
})
_PUSH_EVENTS: frozenset[str] = frozenset({"push"})

# The bound marker: the hex run after `HARNESS-UPDATE-APPROVED@`, at least
# git's seven-character short form and at most a full sha, ended by anything
# that is not a letter or digit (a run glued to a letter is not a binding).
# Bounded quantifier, no alternation: linear on any title.
_APPROVED_SHA_RE = re.compile(
    re.escape(APPROVAL_MARKER) + r"@([0-9a-fA-F]{7,40})(?![0-9A-Za-z])"
)


def approved_shas(title: str) -> list[str]:
    """Every head a PR title's markers approve, in title order: each hex run
    (7 to 40 chars, any case) after ``HARNESS-UPDATE-APPROVED@``, lower-cased.
    Empty when the title carries no BOUND marker -- a bare marker included: on
    a pull request the bare form is the force-push residual this binding
    closes (DEF-338). A title may carry more than one binding: a reviewer who
    APPENDS the re-binding after a force-push rather than replacing the stale
    one has still bound the new head, so the gate reads all of them."""
    return [m.group(1).lower() for m in _APPROVED_SHA_RE.finditer(title or "")]


def approved_sha(title: str) -> str | None:
    """The first bound head in ``title`` (see ``approved_shas``), or ``None``."""
    shas = approved_shas(title)
    return shas[0] if shas else None


def pr_head_sha(env: dict[str, str]) -> str:
    """The head under review, as the deployed workflow forwards it
    (``PR_HEAD_SHA`` from ``github.event.pull_request.head.sha``, the
    merge-queue head as the alternate), lower-cased; ``""`` when absent,
    blank, or not shaped like a commit (fewer than seven hex characters, or
    anything that is not hex), which the PR path treats as a failed-closed
    input rather than a satisfied one -- a malformed head would otherwise be
    printed back as a fragment no binding could ever match."""
    head = (env.get("PR_HEAD_SHA") or "").strip().lower()
    if len(head) < 7 or any(c not in "0123456789abcdef" for c in head):
        return ""
    return head


def _approval_marker_present(env: dict[str, str], cwd: str | None = None) -> bool:
    """Event-allowlisted approval-marker check (BC-032), bound to the head
    under review on PR-like events (DEF-338)."""
    event = env.get("GITHUB_EVENT_NAME", "")
    if event in _PR_EVENTS:
        head = pr_head_sha(env)
        return bool(head) and any(
            head.startswith(sha) for sha in approved_shas(env.get("PR_TITLE", ""))
        )
    if event in _PUSH_EVENTS:
        return APPROVAL_MARKER in head_commit_message(cwd)
    return False


def approval_present(env: dict[str, str], cwd: str | None = None) -> bool:
    """Backwards-compatible wrapper around ``_approval_marker_present``.

    Retained so any external caller (test suite, future tooling) that
    imported the OR-logic predicate still resolves. The body now
    delegates to the trigger-aware check; the OR-logic itself is gone.
    """
    return _approval_marker_present(env, cwd=cwd)


# ---------------------------------------------------------------------------
# Repo-posture scoping for the approval marker (operator ruling, 2026-08-02).
#
# THE RULE:
#   pull_request (and PR-like) | any repo   | marker REQUIRED  (unchanged)
#   push                       | adopter    | marker REQUIRED  (unchanged)
#   push                       | self-host  | marker NOT required   <- the change
#   kill-switch / governance scans          | UNCONDITIONAL    (unchanged)
#
# Rationale, stated so it can be argued with: on a direct push the pusher
# already holds write access, and anyone with write access can simply TYPE the
# marker -- so on that path it buys ceremony, not security. Its value is
# entirely on the PR path, where the author is not necessarily trusted.
# Meanwhile on the self-host repo the gate fires constantly (measured
# 2026-08-02: 35 of the last 60 commits, 58%, touch a protected path). A gate
# satisfied on the majority of its population stops discriminating and trains
# the maintainer to route around it -- the born-weak pattern arriving from the
# opposite direction. Consistent with docs/STANDING_PRINCIPLES.md #2
# (toolbelt, not security boundary).
#
# DELIBERATELY IMPLEMENTED AS A SEPARATE PREDICATE. `_approval_marker_present`
# answers "is the marker present?"; this answers "is it required?". Folding the
# posture into the former would make it return True with no marker present --
# a function lying about its own name, and BC-032's two attempts target it
# directly. Both BC-032 attempts are `pull_request` and `workflow_dispatch`;
# NEITHER is a push, so this change cannot affect them.
#
# The 5-signal detector below is an INLINE MIRROR of
# tools/cc/hooks/_hook_utils.py::is_self_host_repo (itself mirroring
# espalier.surface_contract). ci_guard has zero sibling imports by contract --
# it is copied verbatim and must run standalone -- and _hook_utils lives in a
# SUBDIRECTORY, so importing it would create the deploy-subset hazard
# tools/cc/CLAUDE.md warns about ("a script COPIED without its sibling deps
# crashes SILENTLY"). Same idiom as _ci_decode_bom and _GOVERNANCE_BLOCKING_HOOKS
# above. Parity is pinned by tests/test_ci_guard.py.
#
# ALL FIVE SIGNALS ARE REQUIRED. Signals 1-4 are cheap; signal 5 (the
# write_guard.py prefix SHA) is the one that matters and the one it is tempting
# to drop. espalier/_self_host_fingerprint.py names the exact hole a 4-signal
# version leaves: "a user repo named espalier-harness with empty stub
# directories would acquire the elevated self-host posture."
# ---------------------------------------------------------------------------

# INLINE literal mirror of tools/cc/hooks/_self_host_fingerprint.py.
# Both must be refreshed in lockstep whenever write_guard.py changes.
_CI_WRITE_GUARD_PREFIX_SHA256 = (
    "d72ea5ffa4aba60812c9c37530491eece48a6a44c2e48930932883feca3300ff"
)
_CI_WRITE_GUARD_PREFIX_BYTES = 200

_CI_PYPROJECT_NAME_LINE = re.compile(r"""^\s*name\s*=\s*["']([^"']+)["']""")


def _plural(n: int, singular: str) -> str:
    """``"<n> <word>"``, pluralised on the count. Mirror of
    ``_hook_utils.plural``'s regular form: this file runs standalone in an
    adopter's CI and imports nothing from the hooks, so the ``(s)`` idiom
    the adopter read in their log until DEF-410k is spelled out here."""
    return f"{n} {singular}{'' if n == 1 else 's'}"


def _ci_project_name_from_pyproject(text: str) -> str | None:
    """Extract project.name via stdlib regex. Mirror of _hook_utils's twin.

    Avoids tomllib/tomli to stay stdlib-only on 3.10. Only `name = ...` lines
    inside `[project]` / `[tool.poetry]` match, so a dependency line such as
    `dependencies = ["espalier-harness>=1.0"]` is not picked up.
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
        if (m := _CI_PYPROJECT_NAME_LINE.match(line)):
            return m.group(1)
    return None


def _ci_write_guard_prefix_matches_pin(root: Path) -> bool:
    """Signal 5: SHA-256 of write_guard.py's first 200 bytes vs the pin."""
    path = root / "tools" / "cc" / "hooks" / "write_guard.py"
    if not path.is_file():
        return False
    try:
        prefix = path.read_bytes()[:_CI_WRITE_GUARD_PREFIX_BYTES]
    except OSError:
        return False
    return hashlib.sha256(prefix).hexdigest() == _CI_WRITE_GUARD_PREFIX_SHA256


def _ci_is_self_host_repo(root: Path) -> bool:
    """5-signal self-host detector (all required).

    False on ANY mismatch, which yields adopter behaviour — the marker stays
    REQUIRED. That is the safe direction: a detector failure tightens the gate
    rather than loosening it.
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
        # UnicodeDecodeError is CAUGHT here deliberately, and the except-list
        # is byte-identical to the SoT's (espalier.surface_contract). DRIVEN:
        # without it a UTF-16 pyproject.toml — a Windows editor or a
        # PowerShell Out-File produces one — raises straight out of run() and
        # the merge gate exits 1 with a traceback instead of a verdict.
        # The SoT already caught it; BOTH tools/cc copies did not, so the
        # defense existed at one of three sites (docs/STANDING_PRINCIPLES.md
        # #8 — class-fix scope). Fixed here and in
        # tools/cc/hooks/_hook_utils.py in the same change.
        #
        # NOT made BOM-tolerant, deliberately. `_ci_decode_bom` sits 250 lines
        # above and would "fix" a BOM'd pyproject here — but the SoT decodes
        # plain utf-8, so a BOM'd file yields "﻿[project]", the section
        # never matches, and the SoT returns False (adopter posture). Decoding
        # the BOM here would make this copy return True where the SoT and the
        # hook twin both return False: one mirror smarter than its source is
        # exactly the drift the parity tests exist to catch. All three sites
        # therefore agree — a BOM'd pyproject yields adopter posture
        # everywhere, which fails CLOSED. Changing that is a change to the
        # SoT's detection semantics and belongs in its own pack.
        text = pyproject.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    name = _ci_project_name_from_pyproject(text)
    if name is None:
        return False
    if name.strip().lower() not in {"espalier-harness", "espalier_harness"}:
        return False
    return _ci_write_guard_prefix_matches_pin(root)


def approval_marker_required(env: dict[str, str], cwd: str | None = None) -> bool:
    """Is the approval marker required for THIS event on THIS repo?

    Returns False only for a push on the self-host repo. Every other
    combination — every PR-like event anywhere, every push on an adopter repo,
    and every unrecognised/unprivileged trigger — returns True.
    """
    event = env.get("GITHUB_EVENT_NAME", "")
    if event not in _PUSH_EVENTS:
        return True
    return not _ci_is_self_host_repo(Path(cwd) if cwd else Path.cwd())


# ---------------------------------------------------------------------------
# Dependabot allowance (Horn A).
#
# .github/workflows/ is a PROTECTED_PREFIX and .github/dependabot.yml schedules
# a weekly `github-actions` ecosystem update, so EVERY Dependabot SHA-bump PR
# touches a protected path. On a pull_request the only accepted marker source
# is env.PR_TITLE, and Dependabot's generated title is "Bump actions/checkout
# from X to Y" -- no marker. Left alone, Harness Guard fails on every
# dependency PR from the first week the repo is public, and the maintainer
# either retitles bot PRs forever or learns to ignore a red gate. "Maintainer
# trained to ignore a red gate" is the exact failure this harness exists to
# prevent, and a red on a public repo's PR list is visible to everyone.
#
# The allowance is narrow by construction -- ALL THREE must hold:
#   1. the actor is exactly `dependabot[bot]`
#   2. every changed path is a .github/workflows/*.yml file
#   3. every changed LINE is a `uses:` ref (plus its comment tail)
# Human approval is then the merge itself, plus the test/release checks.
#
# Framing (docs/STANDING_PRINCIPLES.md #2): this is a workflow toolbelt, not a
# security boundary, so "a bot identity could be spoofed" is not the governing
# objection -- an attacker who can forge GITHUB_ACTOR in CI has already won.
# Conditions 2 and 3 are kept anyway because they cost nothing and bound the
# allowance to the shape Dependabot actually produces.
#
# REJECTED ALTERNATIVES, recorded so they are not re-proposed:
#   Horn B -- drop .github/workflows/ from PROTECTED_PREFIXES for PR events.
#     Too wide: it removes HUMAN protection on the same path, which is the one
#     thing this must not do.
#   Horn C -- remove the github-actions ecosystem from dependabot.yml. Removes
#     the friction by removing the dependency updates; wrong trade on a public
#     repo where stale pinned actions are a real maintenance cost.
# ---------------------------------------------------------------------------

_DEPENDABOT_ACTOR = "dependabot[bot]"
_WORKFLOW_YML_RE = re.compile(r"^\.github/workflows/[^/]+\.ya?ml$")
# A `uses:` line: group(1) is the action IDENTITY (owner/name, before the `@`),
# which must be IDENTICAL across the diff; only the ref after `@` may move.
# A trailing `# vX.Y.Z` comment rides on the same line and is not separately
# matched — this repo (and Dependabot) both put it there.
_USES_LINE_RE = re.compile(r"^\s*(?:-\s*)?uses:\s*([^@\s]+)(?:@(\S+))?")


def _ci_changed_lines(
    base: str, cwd: str | None = None
) -> tuple[list[str], list[str]] | None:
    """(added, removed) content lines of the diff, or None if git fails.

    None means "cannot tell", and every caller must treat that as NOT eligible
    for the allowance — a diff we cannot read is not a diff we can approve.
    Added and removed are kept SEPARATE so the caller can compare the two
    sides; flattening them together loses exactly the information needed to
    tell a version bump from an action swap.
    """
    proc = _git(["diff", "--unified=0", f"{base}..HEAD"], cwd=cwd)
    if proc.returncode != 0:
        return None
    added: list[str] = []
    removed: list[str] = []
    for line in proc.stdout.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added.append(line[1:])
        elif line.startswith("-"):
            removed.append(line[1:])
    return added, removed


def _ci_action_identities(lines: list[str]) -> list[str] | None:
    """Sorted action identities (the `owner/name` before `@`), or None.

    None means at least one line is not a `uses:` line, which disqualifies the
    whole diff — the caller must not treat it as an empty set.
    """
    ids: list[str] = []
    for line in lines:
        m = _USES_LINE_RE.match(line)
        if not m:
            return None
        ids.append(m.group(1))
    return sorted(ids)


def dependabot_action_bump_allowed(
    env: dict[str, str], paths: list[str], base: str, cwd: str | None = None
) -> bool:
    """True only for a genuine Dependabot action-SHA bump. Fails closed.

    ``paths`` must be EVERY changed path, not just the protected ones: a real
    action bump touches workflow YAML and nothing else, and scoping this to
    protected paths alone would let an unrelated file ride along on the
    allowance.

    The identity check is load-bearing. Matching only the SHAPE of a `uses:`
    line accepts an action *swap* — `actions/checkout@sha` →
    `attacker/evil@sha` is two well-formed `uses:` lines — which is wider than
    this function's own name and was verified reachable before this arm
    existed (3 of 3 swap shapes allowed, including appending a brand-new
    `uses:` line, which shows as an addition with no matching removal).
    Requiring the sorted identity multiset to be EQUAL on both sides permits
    only a ref change, which is precisely what Dependabot emits.
    """
    if env.get("GITHUB_ACTOR", "") != _DEPENDABOT_ACTOR:
        return False
    if not paths:
        return False
    if not all(_WORKFLOW_YML_RE.match(p) for p in paths):
        return False
    lines = _ci_changed_lines(base, cwd=cwd)
    if lines is None:
        return False
    added = [ln for ln in lines[0] if ln.strip()]
    removed = [ln for ln in lines[1] if ln.strip()]
    if not added:
        return False
    added_ids = _ci_action_identities(added)
    removed_ids = _ci_action_identities(removed)
    if added_ids is None or removed_ids is None:
        return False
    return added_ids == removed_ids


_SETTINGS_FILES_FOR_KILL_SWITCH: tuple[str, ...] = (
    ".claude/settings.json",
    ".claude/settings.local.json",
)

_NOOP_COMMANDS = frozenset({"", ":", "true", "/bin/true", "/usr/bin/true"})
_EXIT_NOOP_RE = re.compile(r"^\s*exit\s+\d+\s*$")

# The blocking governance hooks whose deletion from a committed
# .claude/settings.json silently removes a DENY/blocking gate while
# the hook *file* stays on disk. INLINE literal mirror of
# espalier.harness_config.GOVERNANCE_BLOCKING_HOOKS — ci_guard has ZERO espalier
# imports (it is copied verbatim and runs standalone), so the SoT cannot be
# imported here. The two copies are parity-pinned by
# tests/test_ci_guard.py::test_governance_mirror_matches_sot.
_GOVERNANCE_BLOCKING_HOOKS: dict[str, str] = {
    "write_guard.py": "PreToolUse",
    "plan_guard.py": "PreToolUse",
    "config_guard.py": "ConfigChange",
    "stop_gate.py": "Stop",
}
_HOOKS_DIR_REL = "tools/cc/hooks"


def _is_noop(command) -> bool:  # type: ignore[no-untyped-def]
    if not isinstance(command, str):
        return False
    s = command.strip()
    if s in _NOOP_COMMANDS:
        return True
    return bool(_EXIT_NOOP_RE.match(s))


# The 10 hook events Espalier governs. An empty top-level list for a GOVERNED
# event neuters a deployed hook (a kill-switch); an empty list for a NON-governed
# event is the adopter's own config, identical to omitting the key — NOT a
# kill-switch, so flagging it false-fails a first adopter PR in the adopter's own
# CI. Forced copy of hooks/_integrity._ESPALIER_GOVERNED_EVENTS (which mirrors
# espalier.harness_config.HOOK_EVENTS); ci_guard is zero-espalier-import, so a
# 3-way parity test pins all three equal
# (tests/test_ci_guard.py::TestGovernanceMirrorParity).
_ESPALIER_GOVERNED_EVENTS = frozenset({
    "SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
    "ConfigChange", "Stop", "SubagentStop", "PostCompact", "SubagentStart",
    "PostToolUseFailure",
})


def _scan_settings_file_for_kill_switch(rel: str, root: Path) -> list[str]:
    """Local kill-switch scanner — mirrors hooks/_integrity._find_kill_switches.

    Kept inline so ci_guard remains independent of any other tools/cc/
    module. Returns a list of "rel: reason" findings.
    """
    path = root / rel
    if not path.exists():
        return []
    try:
        # decode_bom (UTF-8/16/32) so a BOM'd settings.json does not EVADE the
        # kill-switch scan (a BOM + disableAllHooks:true would parse-fail and slip
        # through — the sibling fail-open to the wiring oracle).
        data = json.loads(_ci_decode_bom(path.read_bytes()))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    findings: list[str] = []
    if data.get("disableAllHooks") is True:
        findings.append(f"{rel}: disableAllHooks: true")
    perms = data.get("permissions")
    if isinstance(perms, dict):
        mode = perms.get("defaultMode")
        if isinstance(mode, str) and mode == "bypassPermissions":
            findings.append(f'{rel}: permissions.defaultMode: "bypassPermissions"')
    hooks = data.get("hooks")
    if isinstance(hooks, dict):
        for event, entries in hooks.items():
            # Empty top-level list: a kill-switch ONLY for a governed event (it
            # neuters a deployed Espalier hook). An empty list for a non-governed
            # event is the adopter's own config — do not false-fail their CI.
            if isinstance(entries, list) and not entries:
                if event in _ESPALIER_GOVERNED_EVENTS:
                    findings.append(f"{rel}: hooks.{event} is an empty list")
                continue
            if not (isinstance(entries, list) and entries):
                continue
            if all(
                isinstance(e, dict)
                and isinstance(e.get("hooks"), list)
                and not e["hooks"]
                for e in entries
            ):
                findings.append(
                    f"{rel}: hooks.{event} entries all have empty inner hooks list"
                )
                continue
            cmds: list[object] = []
            broke = False
            for e in entries:
                if not isinstance(e, dict):
                    broke = True
                    break
                inner = e.get("hooks")
                if not isinstance(inner, list) or not inner:
                    broke = True
                    break
                for c in inner:
                    if isinstance(c, dict):
                        cmds.append(c.get("command"))
                    else:
                        broke = True
                        break
                if broke:
                    break
            if not broke and cmds and all(_is_noop(c) for c in cmds):
                findings.append(f"{rel}: hooks.{event} commands are all no-ops")
    return findings


def scan_committed_kill_switches(cwd: str | None = None) -> list[str]:
    """Scan tracked settings files for kill-switch settings."""
    root = Path(cwd) if cwd else Path.cwd()
    out: list[str] = []
    for rel in _SETTINGS_FILES_FOR_KILL_SWITCH:
        out.extend(_scan_settings_file_for_kill_switch(rel, root))
    return out


def scan_unreadable_settings(cwd: str | None = None) -> list[str]:
    """Committed settings files the kill-switch scan could not READ.

    Deliberately separate from ``scan_committed_kill_switches``. "I found a
    kill switch" and "I could not tell whether there is one" are different
    verdicts, and folding the second into the first suppressed real findings:
    main() returns immediately on a kill-switch hit, so an unreadable file
    would short-circuit the governance-wiring report that has its own, more
    specific things to say about the same commit.

    Both are still merge-blocking. The gap this closes is narrow and real: an
    unparseable ``.claude/settings.json`` committed WITH the
    HARNESS-UPDATE-APPROVED marker exited 0. The protected-path rule alone
    does not cover it (the marker is exactly what waives that rule), and the
    governance-wiring oracle does not either (it needs the hook scripts in the
    same commit; a settings-only commit slips past). Verified both directions
    before and after. Non-interactive gate, so unlike ``write_guard`` there is
    no lockout risk in failing closed.
    """
    root = Path(cwd) if cwd else Path.cwd()
    out: list[str] = []
    for rel in _SETTINGS_FILES_FOR_KILL_SWITCH:
        path = root / rel
        if not path.exists():
            continue
        try:
            data = json.loads(_ci_decode_bom(path.read_bytes()))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            out.append(f"{rel}: unparseable settings file (kill-switch scan could not run)")
            continue
        if not isinstance(data, dict):
            out.append(
                f"{rel}: settings file is not a JSON object "
                f"(kill-switch scan could not run)"
            )
    return out


_CI_MUTATION_MATCHER_TOOLS = ("Write", "Edit", "NotebookEdit")


def _ci_is_python_interpreter(token: str) -> bool:
    if not token or any(c.isspace() for c in token):
        return False
    base = token.replace("\\", "/").rsplit("/", 1)[-1]
    return base == "py" or base.startswith("python")


def _ci_normalize_rel(token: str) -> str:
    """Strip ${CLAUDE_PROJECT_DIR}/ and a leading ./ — byte-parity with
    surface_contract._normalize(_strip_project_dir_prefix(...)). The leading-./
    strip is load-bearing for doctor/ci parity."""
    t = token.replace("\\", "/")
    for prefix in ("$CLAUDE_PROJECT_DIR/", "${CLAUDE_PROJECT_DIR}/"):
        if t.startswith(prefix):
            t = t[len(prefix):]
            break
    if t.startswith("./"):
        t = t[2:]
    return t


def _ci_hook_executes_script_path(hook: dict) -> str | None:  # type: ignore[type-arg]
    """Stdlib-only mirror of surface_contract._hook_executes_script_path
    (zero-imports rule). Recognizes ONLY the canonical exec form — type EXACTLY
    "command", command a BARE python interpreter, args[0] the .py program —
    and fails CLOSED on shell-form / flag-prefixed / wrapper entries. Closes the
    -c/-m + shell-control-operator fail-opens by not parsing shell at all (the
    construct space is undecidable; the canonical shape is finite).

    ⚠ ABSENT `type` is NOT "command" — driven on real Claude Code 2.1.247, an
    untyped entry does not run. Both this mirror and its engine twin modelled it
    as live, which was a fail-OPEN on both sides at once."""
    if not isinstance(hook, dict):
        return None
    if hook.get("type") != "command":
        return None
    cmd = hook.get("command")
    if not (isinstance(cmd, str) and _ci_is_python_interpreter(cmd)):
        return None
    args = hook.get("args")
    if not isinstance(args, list) or not args:
        return None
    first = args[0]
    if not isinstance(first, str):
        return None
    path = _ci_normalize_rel(first)
    return path if path.endswith(".py") else None


def _ci_matcher_covers_mutations(matcher: str) -> bool:
    """Mirror of surface_contract.matcher_covers_mutations (zero-imports).
    fullmatch (not search) = stricter / fail-CLOSED on substring-only matchers."""
    if matcher in ("", "*", ".*"):
        return True
    try:
        pat = re.compile(matcher)
    except re.error:
        return False
    return all(pat.fullmatch(tool) for tool in _CI_MUTATION_MATCHER_TOOLS)


# Per-hook canonical PreToolUse matcher (inline mirror of
# espalier.harness_config.CANONICAL_HOOK_WIRING[script]["matcher"], zero-imports;
# parity-pinned by tests/test_ci_guard.py). write_guard MUST fire on every tool
# (its kill-switch reach); plan_guard must cover the mutation tools.
_CI_CANONICAL_PRETOOLUSE_MATCHERS: dict[str, str] = {
    "write_guard.py": "*",
    "plan_guard.py": "Write|Edit|NotebookEdit",
}


def _ci_matcher_covers_canonical(deployed: str, canonical: str) -> bool:
    """Mirror of surface_contract.matcher_covers_canonical (zero-imports). The
    deployed matcher must be at least as broad as the hook's canonical matcher:
    canonical fire-on-all (write_guard "*") → deployed must fire on all;
    canonical names tools (plan_guard) → deployed must cover the mutation set."""
    fire_all = ("", "*", ".*")
    if canonical in fire_all:
        return deployed in fire_all
    return _ci_matcher_covers_mutations(deployed)


def _ci_hook_object_schema_error(hook) -> str | None:  # type: ignore[no-untyped-def]
    """Stdlib-only mirror of surface_contract._hook_object_schema_error."""
    if not isinstance(hook, dict):
        return "a hook entry is %s, not an object" % type(hook).__name__
    htype = hook.get("type")
    if htype == "command":
        if not isinstance(hook.get("command"), str):
            return 'a "command" hook has no string "command"'
        args = hook.get("args")
        if args is not None and not isinstance(args, list):
            return ('a "command" hook\'s "args" is %s, not a list'
                    % type(args).__name__)
        return None
    if htype == "prompt":
        if not isinstance(hook.get("prompt"), str):
            return 'a "prompt" hook has no string "prompt"'
        return None
    shown = "<absent>" if htype is None else repr(htype)
    return 'a hook entry has type %s (expected "command" or "prompt")' % shown


def _ci_hooks_config_voided_by(hooks_cfg) -> str | None:  # type: ignore[no-untyped-def]
    """Stdlib-only mirror of surface_contract.hooks_config_voided_by.

    Claude Code schema-validates the WHOLE hooks block and refuses all of it if
    any group or hook object fails — silently. Driven on CC 2.1.247 with
    controls: a typed SessionStart hook did not fire while a malformed entry sat
    under PostToolUse. Mirrored here rather than left engine-only because
    ci_guard is the merge gate: a fix on one side of a parity-locked pair is a
    silent split, and this pair already split once on this very shape.

    ⚠ Behaviour must stay byte-equal to the engine twin — pinned by
    tests/test_surface_contract.py::TestHookTypeIsRequiredAndVoidsTheWholeFile.
    """
    if not isinstance(hooks_cfg, dict):
        return None
    for event, entries in hooks_cfg.items():
        if not isinstance(entries, list):
            return ("hooks.%s is %s, not a list of hook groups"
                    % (event, type(entries).__name__))
        for entry in entries:
            if not isinstance(entry, dict):
                return ("hooks.%s: a hook group is %s, not an object"
                        % (event, type(entry).__name__))
            if "matcher" in entry and not isinstance(entry["matcher"], str):
                return ('hooks.%s: a group\'s "matcher" is %s, not a string'
                        % (event, type(entry["matcher"]).__name__))
            if "hooks" not in entry:
                return 'hooks.%s: a group has no "hooks" list' % event
            hooks_list = entry["hooks"]
            if not isinstance(hooks_list, list):
                return ('hooks.%s: a group\'s "hooks" is %s, not a list'
                        % (event, type(hooks_list).__name__))
            for hook in hooks_list:
                problem = _ci_hook_object_schema_error(hook)
                if problem:
                    return "hooks.%s: %s" % (event, problem)
    return None


def _scan_settings_for_missing_governance_events(rel: str, root: Path) -> list[str]:
    """Flag a committed settings.json that drops or neuters a blocking governance
    gate while the hook FILE stays on disk.

    A gate is "effectively wired" only when an entry EXECUTES the canonical
    ``tools/cc/hooks/<script>`` via a python interpreter under the right event
    (and, for PreToolUse, with a matcher that fires on Write/Edit/NotebookEdit).
    The kill-switch loop only flags PRESENT-but-empty keys, and a path left as
    bait in a no-op/echo/commented/wrong-type/wrong-matcher entry reads as wired
    to a path-only scan (the re-attack fail-opens). Reads on-disk directly
    — in CI only committed files are present, so this checks the committed state."""
    path = root / rel
    # A DANGLING symlink (lexists True, exists False) is present-but-broken, not
    # absent — fall through and fail CLOSED (flag the deployed gates), matching
    # doctor. Truly-absent → init/presence owns it.
    if not (path.exists() or path.is_symlink()):
        return []
    # The file EXISTS, so fail CLOSED on any shape we cannot prove wires the
    # gates. A malformed / non-dict / no-`hooks` settings
    # is the MOST complete neutering (all gates dead at once) — it must flag every
    # deployed gate, mirroring doctor. Do NOT early-return [] on a bad shape:
    # build an empty wirings set and fall through to the completeness loop.
    wirings: list[tuple[str, str, str]] = []
    try:
        # decode_bom (UTF-8/16/32 BOM-tolerant) — a byte-canonical but BOM'd
        # settings.json must not false-flag every gate.
        data = json.loads(_ci_decode_bom(path.read_bytes()))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        data = None
    hooks = data.get("hooks") if isinstance(data, dict) else None
    voided_by = _ci_hooks_config_voided_by(hooks)
    if isinstance(hooks, dict) and voided_by is None:
        for event, entries in hooks.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                # Absent matcher → "" (fire-on-all, canonical for no-matcher
                # events). PRESENT but non-string → malformed → a sentinel that
                # fails coverage (fail-closed), not "" which would read covered.
                if "matcher" in entry:
                    matcher = entry["matcher"]
                    if not isinstance(matcher, str):
                        matcher = "\x00invalid"
                else:
                    matcher = ""
                inner = entry.get("hooks")
                if not isinstance(inner, list):
                    continue
                for hook in inner:
                    script_path = _ci_hook_executes_script_path(hook)
                    if script_path:
                        wirings.append((str(event), script_path, matcher))
    findings: list[str] = []
    if voided_by:
        # Named FIRST and named SPECIFICALLY. The per-gate wall below is
        # correct but unactionable here: every gate reads dead, and the entry
        # that killed them may be one this project does not manage. A verdict
        # that lists four dead gates without pointing at the one offending
        # `type` sends the operator to rewrite wiring that is already right.
        findings.append(
            f"{rel}: {voided_by} -- Claude Code loads NO hooks at all from a "
            "settings file containing a hook entry whose 'type' is not exactly "
            '"command" (absent counts), so EVERY governance gate below is dead, '
            "including the ones whose own wiring is correct"
        )
    hooks_dir = root / _HOOKS_DIR_REL
    for script, event in sorted(_GOVERNANCE_BLOCKING_HOOKS.items()):
        if not (hooks_dir / script).is_file():
            continue  # not deployed → out of scope
        canonical = f"{_HOOKS_DIR_REL}/{script}"
        canonical_matcher = _CI_CANONICAL_PRETOOLUSE_MATCHERS.get(script, "")
        live = any(
            ev == event and sp == canonical
            and (event != "PreToolUse"
                 or _ci_matcher_covers_canonical(mt, canonical_matcher))
            for (ev, sp, mt) in wirings
        )
        if not live:
            findings.append(
                f"{rel}: blocking governance hook {script} is present on disk "
                f"but has no executable, correctly-matched wiring under the "
                f"{event} event "
                + (
                    # Mirrors doctor exactly -- see the note there. The generic
                    # cause list is false on a voided tree and contradicts the
                    # summary finding emitted above it.
                    "(the whole hooks block is void -- see the first finding "
                    "above)"
                    if voided_by else
                    "(a deleted event key, a no-op/echo/commented command, a "
                    "stale-copy path, or a tool-excluding matcher silently "
                    "disables the gate)"
                )
            )
    return findings


def scan_missing_governance_events(cwd: str | None = None) -> list[str]:
    """Scan the committed project .claude/settings.json for a dropped blocking
    governance gate. Only the project file — settings.local is a gitignored
    local override, not the shipped governance contract."""
    root = Path(cwd) if cwd else Path.cwd()
    return _scan_settings_for_missing_governance_events(".claude/settings.json", root)


def run(env: dict[str, str], cwd: str | None = None) -> int:
    # LAYERED GOVERNANCE DEFENSE. `espalier init` gitignores
    # .claude/settings.json (it records a machine-detected interpreter name), so in a
    # clean CI checkout the file is ABSENT and the two scans below read nothing.
    # That is by design, not a hole: the gitignore is the PRIMARY foreclosure (a
    # kill-switch there never reaches a commit by the normal path), config_guard
    # is the live ConfigChange deny, and these CI scans are the BACKSTOP for a
    # deliberate `git add -f` that force-tracks settings.json into the commit.
    # EXCEPTION (DEF-11): on a repo that already tracked .claude/settings.json
    # before `espalier init`, init withholds the gitignore entry (ignoring a
    # tracked path protects nothing), so the file IS present in CI and these
    # scans become the PRIMARY gate rather than the backstop.
    # The committable-settings model that would make these the *primary* CI gate
    # (so adopter CI verifies hook-wiring directly) is scoped as a separate change
    # — do not re-frame these as un-overridable primary gates here or in CLAUDE.md.
    #
    # Unconditional kill-switch check — fails even if HARNESS-UPDATE-APPROVED
    # is present. A force-added kill-switch cannot survive the merge regardless
    # of approval.
    kill_switches = scan_committed_kill_switches(cwd=cwd)
    if kill_switches:
        print(
            "Harness Guard: kill-switch settings cannot be committed to the "
            "public project. The HARNESS-UPDATE-APPROVED marker does NOT "
            "override this check."
        )
        print("")
        print("Kill-switch findings:")
        for f in kill_switches:
            print(f"  - {f}")
        print("")
        print(
            f"Remove the offending {'setting' if len(kill_switches) == 1 else 'settings'} "
            "before merging. Locally, "
            "`disableAllHooks: true` is sometimes used to temporarily edit "
            "harness files; it must not survive into a commit."
        )
        return 2

    # Unconditional governance-event completeness check.
    # Like the kill-switch check, the HARNESS-UPDATE-APPROVED marker does NOT
    # override it: the real fail-open is an *approved* harness change that
    # accidentally deletes a blocking event key (the protected-path + approval
    # path would let that through). A legitimate hook removal updates the SoT
    # (harness_config.GOVERNANCE_BLOCKING_HOOKS + this mirror) first, so the
    # check no longer requires it — the marker is not the right escape hatch.
    # Runs AFTER the governance scan below so a commit that trips both still
    # gets the wiring detail, which names the specific gates at risk.
    unreadable_settings = scan_unreadable_settings(cwd=cwd)

    missing_gov = scan_missing_governance_events(cwd=cwd)
    if missing_gov:
        print(
            "Harness Guard: .claude/settings.json drops a blocking governance "
            "gate (a deleted/unwired event key). The HARNESS-UPDATE-APPROVED "
            "marker does NOT override this check."
        )
        print("")
        print("Governance wiring findings:")
        for f in missing_gov:
            print(f"  - {f}")
        print("")
        print(
            "Re-wire the hook under its canonical event (re-run `espalier init "
            ".` or restore the event key). If a hook is being retired, update "
            "espalier.harness_config.GOVERNANCE_BLOCKING_HOOKS and ci_guard's "
            "_GOVERNANCE_BLOCKING_HOOKS mirror in the same change."
        )
        return 2

    if unreadable_settings:
        print(
            "Harness Guard: a committed settings file cannot be parsed, so the "
            "kill-switch scan could not run on it. 'Could not check' is not "
            "'clean'. The HARNESS-UPDATE-APPROVED marker does NOT override "
            "this check."
        )
        print("")
        print("Unreadable settings findings:")
        for f in unreadable_settings:
            print(f"  - {f}")
        print("")
        print(
            "Fix the JSON (or remove the file) so the gate can read it. An "
            "unparseable settings.json committed WITH the approval marker "
            "previously exited 0 -- the marker waives the protected-path rule, "
            "and the governance-wiring check needs the hook scripts in the "
            "same commit, so a settings-only commit passed both."
        )
        return 2

    base = resolve_base(env, cwd=cwd)
    paths = changed_paths(base, cwd=cwd)
    offenders = [p for p in paths if is_protected(p)]
    if not offenders:
        return 0

    # Repo-posture scoping (operator ruling 2026-08-02). Checked BEFORE the
    # marker because it is the cheaper question and because, when it applies,
    # the marker is irrelevant rather than merely satisfied. Note this runs
    # AFTER both unconditional scans above — the kill-switch and governance
    # gates are never reached by this branch.
    if not approval_marker_required(env, cwd=cwd):
        print(
            f"ci_guard: push on the self-host repo -- approval marker not "
            f"required; {_plural(len(offenders), 'protected path')} allowed. "
            "(The marker remains required for every pull-request event and "
            "for pushes on an adopter repo.)"
        )
        return 0

    if approval_present(env, cwd=cwd):
        print(
            f"ci_guard: approval marker present -- "
            f"{_plural(len(offenders), 'protected path')} allowed."
        )
        return 0

    # Narrow Dependabot allowance: a real action-SHA bump touching only
    # workflow YAML. Checked LAST so it can never widen a human's path.
    # `paths`, not `offenders`: a genuine action bump touches workflow YAML and
    # nothing else. Passing only the protected subset would let an unrelated
    # changed file ride along, and would leave conditions 2 and 3 silently
    # load-bearing for each other.
    if dependabot_action_bump_allowed(env, paths, base, cwd=cwd):
        print(
            f"ci_guard: Dependabot action-SHA bump -- "
            f"{_plural(len(offenders), 'workflow path')} allowed without a "
            "marker. Approval is the merge "
            "itself plus the test/release checks."
        )
        return 0

    print("Harness Guard: protected paths changed without approval marker.")
    print("")
    print("Offending paths:")
    for p in offenders:
        print(f"  - {p}")
    print("")
    # Name the channel THIS event accepts, not both. `_approval_marker_present`
    # is event-allowlisted -- a pull_request reads PR_TITLE only, a push reads
    # the HEAD commit message only -- so the old either/or text listed a
    # refused channel first. A contributor who amended their commit message on
    # a PR re-ran the gate and got byte-identical output, with nothing on
    # screen to say why.
    event = env.get("GITHUB_EVENT_NAME", "")
    if event in _PR_EVENTS:
        # Three cases, each with the one thing to do next on screen: the head
        # never reached the gate; the title approves a different head (a
        # force-push after approval, or a typo); or the title carries no bound
        # marker at all (the bare form included -- DEF-338).
        head = pr_head_sha(env)
        approved = approved_shas(env.get("PR_TITLE", ""))
        if not head:
            channel = (
                "This run did not receive PR_HEAD_SHA (the head under review) as a\n"
                "commit sha, so no title marker can be bound to it. The deployed\n"
                "workflow forwards it in the env block of the 'Check protected paths'\n"
                "step as exactly this line:\n"
                "  PR_HEAD_SHA: ${{ github.event.pull_request.head.sha || "
                "github.event.merge_group.head_sha }}\n"
                "`espalier install-ci` writes the current workflow -- as\n"
                ".github/workflows/harness-guard.yml.new when yours differs, so merge\n"
                "that over yours -- or add the line by hand (github.sha is the MERGE\n"
                "commit on a pull request, not the head). The title still needs\n"
                f"'{APPROVAL_MARKER}@<sha>' for the head under review."
            )
        elif approved:
            channel = (
                f"The PULL REQUEST TITLE approves "
                f"{'head' if len(approved) == 1 else 'heads'} {', '.join(approved)}, but\n"
                f"the head under review is {head[:7]}: a force-push (or a typo)\n"
                "after approval. Re-review this head, then set the title's marker to\n"
                f"'{APPROVAL_MARKER}@{head[:7]}' (replace the stale binding, or add\n"
                "the new one beside it). A force-push is re-bound explicitly, on the\n"
                "PR timeline, instead of passing silently; the binding is\n"
                "self-attested, so it is an audit trail, not independent evidence."
            )
        else:
            channel = (
                f"To allow, include '{APPROVAL_MARKER}@{head[:7]}' in the PULL REQUEST TITLE.\n"
                "The marker names the head it approves, so a force-push after\n"
                "approval goes red until the title is re-bound; a bare\n"
                f"'{APPROVAL_MARKER}' without the head is refused for that reason.\n"
                "Editing the title re-runs this check on the same head; a new push\n"
                "moves the head and needs a new binding. On a pull request the title\n"
                "is the only channel this gate reads -- a marker in the commit\n"
                "message is not consulted."
            )
    elif event in _PUSH_EVENTS:
        channel = (
            f"To allow, include '{APPROVAL_MARKER}' in the HEAD COMMIT\n"
            "MESSAGE. On a direct push that is the only channel this gate\n"
            "reads -- there is no pull request title to consult."
        )
    else:
        channel = (
            f"To allow, include '{APPROVAL_MARKER}@<sha>' (bound to the head under\n"
            f"review) in the pull request title on a pull request, or\n"
            f"'{APPROVAL_MARKER}' in the HEAD commit message on a push.\n"
            f"This run reported GITHUB_EVENT_NAME={event!r}, which this gate\n"
            "does not accept a marker for at all."
        )
    print(channel)
    print("")
    print(
        "The marker is required because these paths are the harness's own\n"
        "enforcement layer: settings, hooks, the integrity manifest and this\n"
        "guard. Marking the change is how a deliberate harness update is told\n"
        "apart from one that quietly loosens the gate.\n"
        "\n"
        "See docs/INSTALL-CI.md for the branch-protection setup and the full\n"
        "protected-path list."
    )
    return 2


def main() -> int:
    try:
        return run(dict(os.environ))
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"ci_guard error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
