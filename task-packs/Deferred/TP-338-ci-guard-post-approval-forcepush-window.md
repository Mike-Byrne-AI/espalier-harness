# TP-338 — ci_guard post-approval force-push window (last_review_sha..HEAD gate)

## Status
- Version target: current (self-host; repo at `0.8.0a13`, i.e. well past the
  documented **post-v0.7** trigger). The residue's own deferral note keyed on
  "post-v0.7" — that gate has arrived.
- Change type: SECURITY-HARDENING (completeness fix on an already-documented,
  manually-mitigated residue) — **not** a live-threat closure on the self-host repo.
- **Kind: PACK** (single self-contained gate extension + its earn-red + doc/mirror sync)
- Derived from: the orphan-intent net `wf_252b9580` (forward-intent with no tracker
  reader), reconciled against the source store — `docs/SHARP_EDGES.md`
  "**Residual risk (deferred to post-v0.7)**" (the `## CI Approval Marker` section,
  fragment `id=ci-trigger-aware-marker`, ~lines 994–1002) which names the exact
  mechanism and the interim manual mitigation, plus the
  `task-packs/CHANGELOG_archive_20260705.md` BC-032 lineage that promised an
  API-history follow-up pack that was never authored.

## Motivation

BC-032 (TP-58, `6ad3668`) closed the *first* force-push laundering window: the
marker check used to be a logical OR over `(head_commit_message, PR_TITLE)`, so a
PR author could force-push the marker text into a new HEAD commit message *after*
a clean review. The trigger-aware allowlist (`_approval_marker_present`) fixed that
by honouring **only** `PR_TITLE` on PR-like events — the title is on the PR timeline
and a force-push cannot edit it.

The documented **residue** is one step deeper and is STILL LIVE (verified in
`tools/cc/ci_guard.py` at HEAD): an author writes an *honest* marker in the PR
title, gets an approval, then force-pushes a HEAD that adds a protected-zone change
(`tools/cc/hooks/…`, `.github/workflows/…`, `.espalier/integrity.json`, …) **after**
approval. `run()` computes `offenders` over `base..HEAD`, sees the honest title, and
`approval_present(...)` returns `True` → **exit 0**. The reviewer never saw the
force-pushed change; the marker (correctly, per its own semantics) does not object.
There is no notion of *what commit was approved* anywhere in `ci_guard` today. The
only current defense is the manual note in SHARP_EDGES: "reviewers MUST re-review
any force-push on a PR that touches protected zones."

**Honest weighing — execute now vs. record as an open decision (STANDING_PRINCIPLES
§2: toolbelt, not security boundary; threat model is operator/AI *mistakes, not
malice*; false-positives and friction outrank closing bypass classes):**

- On the **self-host solo-operator repo the security value is ≈ nil.** This residue
  requires *malice* by someone who already holds PR-write + merge rights — i.e. the
  operator — who has no one to launder approval past. The real payoff here is
  **legibility/completeness**: a documented open gap with only a rot-prone human
  mitigation gets a mechanical gate, letting the SHARP_EDGES residual note retire to
  "closed except in degraded/offline runs."
- The **adopter** payoff is narrow: it matters only for a team with untrusted PR
  authors *and* branch protection whose "Dismiss stale approvals on new commits"
  setting is **off** (the vulnerable config). For everyone else it is inert.
- Cost is **small and low-risk**: three stdlib-`urllib` helpers on an existing gate,
  the **free** GitHub REST API (reviews + compare endpoints — NOT a paid API, NOT
  GH-Actions minutes), and a `pull-requests: read` token scope already carried by the
  Actions default `GITHUB_TOKEN`. The gate **degrades to today's exact behavior**
  (allow + WARN = the existing manual mitigation) everywhere the API isn't reachable
  (local runs, missing token, non-PR event, rate-limit) — so it adds **zero new
  false-positive class** for adopters.

Recommendation: **worth executing now** as a bounded completeness fix *because* the
post-v0.7 trigger explicitly arrived and the mitigation-by-human-memory is the kind
of thing that rots — **but** the operator may equally choose to **record it as an
open decision** (the manual mitigation + SHARP_EDGES note stand) and defer. If
deferred, log the decision in `FORWARD_LEDGER` (owned by the main session, not this
pack). Do **not** frame this as closing a live threat on the self-host repo.

## Scope (in)

### Sub-task 1-A — Workflow env-forward + token scope (smallest; do first)
The gate needs three facts the current workflow does not forward, and one extra
token scope. Edit the **package SoT** `espalier/assets/github/workflows/harness-guard.yml`,
then mirror to the root `.github/workflows/harness-guard.yml`
(`test_root_workflow_mirrors_package` pins asset → root). On the "Check protected
paths" step add `PR_NUMBER`, `PR_HEAD_SHA`, `GITHUB_TOKEN`; at workflow level add
`pull-requests: read` alongside `contents: read`. (`GITHUB_REPOSITORY` and
`GITHUB_API_URL` are Actions default env vars — no forward needed; `GITHUB_TOKEN`
is *not* auto-exported to `env`, so it must be forwarded explicitly.)

### Sub-task 1-B — `ci_guard` post-approval window check (the fix)
Add three stdlib-`urllib` helpers and wire them into `run()`'s marker branch:
resolve the latest APPROVED review's `commit_id` via the reviews API, compare it to
the PR head via the compare endpoint, and **DENY even with an honest marker** when a
protected path appears in `last_review_sha..HEAD`. Fail **soft** (return `None` →
allow + WARN) whenever the window cannot be determined. Re-sync the vendor mirror.

### Sub-task 1-C — Earn-the-red regression tests
Add `TestApprovalMarkerPostApprovalWindow` to `tests/test_ci_guard.py`, driving
`ci_guard.run()` **in-process** (importlib-loaded, per `tests/CLAUDE.md`) with
`_github_api_get` monkeypatched — three cases: (1) protected path in
`review_sha..HEAD` → DENY (reds on unfixed code, which returns 0); (2) approval
covers HEAD (empty compare) → ALLOW; (3) missing token / non-PR event → degrade
(ALLOW + WARN).

### Sub-task 1-D — Retire the SHARP_EDGES residual note + vendor/doc parity
Update the `## CI Approval Marker` "Residual risk" paragraph in `docs/SHARP_EDGES.md`
to reflect the closed state (mechanical gate lands the API-history check;
the manual mitigation now applies **only** to degraded/offline runs where the API is
unreachable). Confirm the fragment `id=ci-trigger-aware-marker` prose still matches
`_approval_marker_present` (unchanged) and that the new function set is described.

## Scope (out)

- **Fail-CLOSED on API-unreachable.** Rejected: a rate-limit, a network flake, a
  wrong token scope, or a local run would then false-block a legitimate PR — exactly
  the friction §2 says outranks closing a malice-only bypass. Degrade-to-manual
  (allow + WARN, matching today's behavior) is the deliberate choice; the guarantee
  is live precisely where it is the guarantee — the repo's own GitHub Actions run,
  where `GITHUB_TOKEN` + the API are always present.
- **Local `git diff last_review_sha..HEAD` fallback for file enumeration.** Rejected:
  a force-push can orphan `last_review_sha` in the checked-out clone, so a local diff
  is unreliable exactly in the attack case. The GitHub **compare endpoint** is
  authoritative (GitHub retains the review's commit). Reason: correctness beats
  reusing `changed_paths`.
- **Diverged/rebased-history over-flag.** When a PR is force-*rebased* (so
  `last_review_sha` is no longer an ancestor of HEAD), the three-dot compare's
  merge-base diff may flag protected paths that were already in the approved range.
  Accepted, not fixed: over-flagging nudges toward re-request-review — the safe
  direction — and only fires on the already-rare "rebased a PR that touches protected
  zones" case. Reason: false-negative-avoidance in the correct direction; low volume.
- **Reviews pagination beyond 100.** The reviews call uses `per_page=100`; a PR with
  >100 reviews whose latest approval is on a later page is not handled. Reason:
  negligible frequency; a pagination loop is disproportionate to the payoff.
- **Double-revert edge (protected path nets zero in `base..HEAD` but is added in
  `review_sha..HEAD`).** The check keys off `offenders` (the existing `base..HEAD`
  scan) via the early `if not offenders: return 0`. A file reverted before approval
  and re-added after nets zero in `base..HEAD` and is skipped. Reason: pathological;
  the manual mitigation covers it; adding an API call to every clean marker-bearing
  PR to catch it is not worth the cost.
- **New bench-corpus row (BC-0XX) + bypass-class-count bump.** BC-032 added a corpus
  row for the *trigger-aware* fix; a symmetric row here would fan out to
  `NUMERIC_CONTRACTS`, `.espalier/freshness.json`, migrations, and the README count
  (the TP-130 fan-out). Deferred to keep this pack tight — the in-process unit test
  is the regression contract; a bench row can follow as its own small change. Reason:
  separate release-gating surface with its own pin obligations.

## Implementation

**Fix 1-B-1 — add the stdlib `urllib` imports** (`tools/cc/ci_guard.py`, import block):

```python
import codecs
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
```

**Fix 1-B-2 — the three post-approval helpers** — insert immediately after
`approval_present` (the block ending `return _approval_marker_present(env, cwd=cwd)`)
and before `_SETTINGS_FILES_FOR_KILL_SWITCH`:

```python
    return _approval_marker_present(env, cwd=cwd)


GITHUB_API_DEFAULT = "https://api.github.com"


def _github_api_get(url: str, token: str, timeout: int = 15):  # type: ignore[no-untyped-def]
    """Authenticated stdlib-only GET -> parsed JSON, or None on ANY failure
    (non-https, network, auth, non-200, decode). Fail-SOFT by design: a None
    return degrades the post-approval check to the interim manual mitigation
    (STANDING_PRINCIPLES §2 — a rate-limit or network flake must never
    false-block a PR). tools/cc/ is zero-espalier-import, so this cannot reuse
    espalier.external_fetch; urllib is stdlib."""
    if not url.startswith("https://"):
        return None
    req = urllib.request.Request(  # noqa: S310 -- https scheme asserted above
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "espalier-ci-guard",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return None


def _last_approved_review_sha(
    api_base: str, repo: str, pr_number: str, token: str
) -> str | None:
    """commit_id of the latest APPROVED review, or None. This fact lives only on
    GitHub's review timeline (not in git) — which is why the API call is
    unavoidable: a force-push cannot rewrite a past review's recorded commit_id."""
    url = f"{api_base}/repos/{repo}/pulls/{pr_number}/reviews?per_page=100"
    data = _github_api_get(url, token)
    if not isinstance(data, list):
        return None
    approved = [
        r for r in data
        if isinstance(r, dict) and r.get("state") == "APPROVED"
        and isinstance(r.get("commit_id"), str) and r["commit_id"]
    ]
    if not approved:
        return None
    return approved[-1]["commit_id"]  # ascending submitted_at order -> last = newest


def _post_approval_protected_changes(
    env: dict[str, str], cwd: str | None = None
) -> list[str] | None:
    """Protected paths added to HEAD AFTER the latest approving review.

    Returns:
      - a non-empty list -> protected paths force-pushed past the approval
        (DENY even with an honest marker).
      - []               -> the approval covers the current HEAD (ALLOW).
      - None             -> the post-approval window cannot be determined
        (non-PR event, missing token/PR metadata, or API unreachable) ->
        degrade to the interim manual mitigation (WARN, do not block).
    """
    if env.get("GITHUB_EVENT_NAME", "") not in _PR_EVENTS:
        return None  # push/other: no review window; branch protection owns it
    token = env.get("GITHUB_TOKEN", "")
    repo = env.get("GITHUB_REPOSITORY", "")
    pr_number = env.get("PR_NUMBER", "")
    head_sha = env.get("PR_HEAD_SHA", "")
    if not (token and repo and pr_number and head_sha):
        return None
    api_base = (env.get("GITHUB_API_URL") or GITHUB_API_DEFAULT).rstrip("/")
    review_sha = _last_approved_review_sha(api_base, repo, pr_number, token)
    if not review_sha:
        return None
    compare = _github_api_get(
        f"{api_base}/repos/{repo}/compare/{review_sha}...{head_sha}", token
    )
    if not isinstance(compare, dict):
        return None
    files = compare.get("files")
    if not isinstance(files, list):
        # 'identical'/'behind' compares can omit `files` — only those two
        # statuses prove no forward change; anything else is unknown -> degrade.
        return [] if compare.get("status") in ("identical", "behind") else None
    changed = [
        f["filename"].replace("\\", "/")
        for f in files
        if isinstance(f, dict) and isinstance(f.get("filename"), str)
    ]
    return [p for p in changed if is_protected(p)]


_SETTINGS_FILES_FOR_KILL_SWITCH: tuple[str, ...] = (
```

**Fix 1-B-3 — wire the check into `run()`'s marker branch** (`tools/cc/ci_guard.py`).
Replace the existing allow-on-marker block:

```python
    offenders = [p for p in paths if is_protected(p)]
    if not offenders:
        return 0
    if approval_present(env, cwd=cwd):
        post_approval = _post_approval_protected_changes(env, cwd=cwd)
        if post_approval:
            print(
                "Harness Guard: protected paths changed AFTER the approving "
                "review. The HARNESS-UPDATE-APPROVED marker in the PR title was "
                "authored honestly, but these paths were force-pushed into HEAD "
                "after the reviewer approved -- the approval does NOT cover them."
            )
            print("")
            print("Post-approval protected paths:")
            for p in post_approval:
                print(f"  - {p}")
            print("")
            print(
                "Re-request review of the current HEAD (a fresh approval advances "
                "last_review_sha). See docs/SHARP_EDGES.md 'CI Approval Marker'."
            )
            return 2
        if post_approval is None:
            print(
                "ci_guard: WARN: post-approval window unverifiable (non-PR event, "
                "missing GITHUB_TOKEN/PR metadata, or GitHub API unreachable). "
                "Reviewers MUST re-review any force-push touching protected zones "
                "-- green CI is NOT independent approval evidence.",
                file=sys.stderr,
            )
        print(
            f"ci_guard: approval marker present -- {len(offenders)} "
            "protected path(s) allowed."
        )
        return 0
    print("Harness Guard: protected paths changed without approval marker.")
```

**Fix 1-A — workflow env-forward + token scope** (`espalier/assets/github/workflows/harness-guard.yml`
is the SoT; mirror byte-for-byte to root). Add the pull-request read scope:

```yaml
permissions:
  contents: read
  pull-requests: read
```

…and the three env forwards on the "Check protected paths" step:

```yaml
        env:
          BASE_SHA: ${{ github.event.pull_request.base.sha }}
          BEFORE_SHA: ${{ github.event.before }}
          PR_TITLE: ${{ github.event.pull_request.title }}
          PR_NUMBER: ${{ github.event.pull_request.number }}
          PR_HEAD_SHA: ${{ github.event.pull_request.head.sha }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GITHUB_EVENT_NAME: ${{ github.event_name }}
        run: python tools/cc/ci_guard.py
```

**Fix 1-C — earn-red test** (`tests/test_ci_guard.py`, new class). Load ci_guard via
`importlib.spec_from_file_location` (per `tests/CLAUDE.md` — never a plain import,
which would drag espalier into its zero-import graph), monkeypatch `_github_api_get`
on the loaded module, and call `mod.run(env, cwd=str(fresh_repo))` in-process. Skeleton
(the deny case; adapt for the allow + degrade cases):

```python
def _load_ci_guard():
    spec = importlib.util.spec_from_file_location("ci_guard_ut", CI_GUARD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestApprovalMarkerPostApprovalWindow:
    def test_protected_change_after_approval_denies_despite_honest_marker(
        self, fresh_repo, monkeypatch
    ):
        _commit(fresh_repo, "tools/cc/hooks/write_guard.py", "x = 1\n", "post-approval")
        mod = _load_ci_guard()

        def fake_get(url, token, timeout=15):
            if "/reviews" in url:
                return [{"state": "APPROVED", "commit_id": "reviewsha0"}]
            if "/compare/" in url:
                return {"status": "ahead",
                        "files": [{"filename": "tools/cc/hooks/write_guard.py"}]}
            return None

        monkeypatch.setattr(mod, "_github_api_get", fake_get)
        env = {
            "GITHUB_EVENT_NAME": "pull_request",
            "PR_TITLE": "HARNESS-UPDATE-APPROVED: honest at review time",
            "GITHUB_TOKEN": "t", "GITHUB_REPOSITORY": "o/r",
            "PR_NUMBER": "1", "PR_HEAD_SHA": "headsha0",
        }
        assert mod.run(env, cwd=str(fresh_repo)) == 2   # unfixed code returns 0 (RED)
```

## Affected symbols

### Changed-semantics
- `tools/cc/ci_guard.py::run` — on an honest marker, DENY when a protected path
  appears in `last_review_sha..HEAD`; WARN-and-allow when the window is undeterminable
- `espalier/_vendor/cc/ci_guard.py::run` — vendor byte-mirror (re-synced, not hand-edited)

### Added-paths
- `tools/cc/ci_guard.py::_github_api_get`
- `tools/cc/ci_guard.py::_last_approved_review_sha`
- `tools/cc/ci_guard.py::_post_approval_protected_changes`
- `espalier/_vendor/cc/ci_guard.py::_post_approval_protected_changes` (+ the two siblings; via `sync_vendor_cc.py`)

### Renamed
- (none)

## Affected literals
- `permissions.pull-requests: read` — new scope in `.github/workflows/harness-guard.yml` + its `espalier/assets/` SoT mirror
- env keys `PR_NUMBER`, `PR_HEAD_SHA`, `GITHUB_TOKEN` — new forwards on the "Check protected paths" step (both workflow copies)
- `GITHUB_API_DEFAULT = "https://api.github.com"` — new module constant in `ci_guard.py` (+ vendor mirror)

## Pass criteria
- **Earn-the-red (1-C, deny case):** against UNFIXED `ci_guard.py`,
  `TestApprovalMarkerPostApprovalWindow::test_protected_change_after_approval_denies_despite_honest_marker`
  asserts `run(...) == 2` but the unfixed code returns `0` → test REDs. After Fix
  1-B, `_post_approval_protected_changes` returns `["tools/cc/hooks/write_guard.py"]`
  → `run(...) == 2` → GREEN.
- **Allow case:** `_github_api_get` compare returns `{"status": "identical"}` (no
  `files`) → `_post_approval_protected_changes` returns `[]` → `run(...) == 0`
  (silent allow).
- **Degrade case:** env lacks `GITHUB_TOKEN` (or `GITHUB_EVENT_NAME` is `push`) →
  returns `None` → `run(...) == 0` **and** the WARN line is emitted to stderr; live
  tree behavior matches today's guard exactly.
- **Vendor parity:** `pytest tests/test_vendor_cc_parity.py` green after
  `python3 scripts/sync_vendor_cc.py` (the ci_guard edit byte-mirrors).
- **Workflow parity:** `pytest tests/test_package_resource_parity.py::TestPackageResourceParity::test_root_workflow_mirrors_package`
  green (asset SoT == root), and `tests/test_shipped_ci_asset_self_contained.py` still
  green (the `verify` job stays un-gated; new env/scope do not change job gating).
- **Full suite:** `pytest -q` green (no new skips); `ruff check .` clean
  (S310 noqa'd with scheme assertion, matching `espalier/external_fetch.py`);
  `python3 -m espalier audit .` 0/0.
- **BC-032 unbroken:** `TestApprovalMarkerForcePushResistance` (13 cases) still green —
  the marker-source routing (`_approval_marker_present`) is untouched.
- **Doc parity (1-D):** `docs/SHARP_EDGES.md` residual paragraph updated; the
  fragment `id=ci-trigger-aware-marker` verify-on-touch contract passes.

## Files touched
- **Modified:**
  - `tools/cc/ci_guard.py` (three helpers + `run()` wiring + urllib imports + constant)
  - `espalier/_vendor/cc/ci_guard.py` — **vendor byte-mirror; regenerate via
    `python3 scripts/sync_vendor_cc.py`, never hand-edit** (`tests/test_vendor_cc_parity.py`
    reds on drift)
  - `espalier/assets/github/workflows/harness-guard.yml` — **package SoT** for the
    workflow (env forwards + `pull-requests: read`)
  - `.github/workflows/harness-guard.yml` — root mirror of the asset SoT
    (`test_root_workflow_mirrors_package` pins asset → root; copy after editing the asset)
  - `docs/SHARP_EDGES.md` — retire the "Residual risk (deferred to post-v0.7)"
    paragraph to reflect the landed gate (manual mitigation now scoped to degraded runs)
  - `tests/test_ci_guard.py` — new `TestApprovalMarkerPostApprovalWindow` class
    (in-process, importlib-loaded, `_github_api_get` monkeypatched)
- **New:** (none)
- **Deleted:** (none)
- **Unmodified-on-purpose:**
  - `espalier/external_fetch.py` — the engine's `urllib` fetcher; NOT reused
    (`tools/cc/` is zero-espalier-import — the API call is hand-rolled with stdlib `urllib`)
  - `tools/cc/ci_guard.py::_approval_marker_present` / `::approval_present` — marker-source
    routing is correct and unchanged; the fix is a NEW window check layered *after* an
    accepted marker, not a change to which marker sources are honoured
  - `.github/workflows/harness-guard.yml` job gating (`detect-source` etc.) — the
    `verify` job stays un-gated so adopters get the check too

## Sub-task ordering
1. **1-A** workflow env-forward + `pull-requests: read` (edit asset SoT → copy to root)
   → `pytest tests/test_package_resource_parity.py -k workflow tests/test_shipped_ci_asset_self_contained.py`
   (green/red checkpoint; surfaces YAML/mirror issues before touching code)
2. **1-B** ci_guard helpers + `run()` wiring → `python3 scripts/sync_vendor_cc.py`
   → `pytest tests/test_vendor_cc_parity.py tests/test_ci_guard.py -q` (BC-032 still green)
3. **1-C** earn-red tests: prove the deny case RED on unfixed `ci_guard.py` first
   (stash/revert 1-B, run, confirm `== 2` fails), restore 1-B, confirm GREEN; add
   allow + degrade cases → `pytest tests/test_ci_guard.py -q`
4. **1-D** SHARP_EDGES residual-note update → `pytest tests/test_documented_claims.py -q`
   + the fragment verify-on-touch contract
5. **final** full `pytest -q` + `ruff check .` + `python3 -m espalier audit .` +
   vendor & workflow parity; stamp Landing

## Estimated effort
- 1-A: ~20 min · 1-B: ~60 min (three helpers + wiring + urllib/noqa) · 1-C: ~45 min
  (deny/allow/degrade + earn-red proof) · 1-D: ~25 min · verify+land: ~20 min.
  **Total ≈ 2.5–3 h.**

## Landing
- State: DRAFT
- Commits:
- Suite:
- Earn-the-red: unfixed `run()` returns 0 on an honest marker with a post-approval
  `tools/cc/` change in `review_sha..HEAD`; the new in-process test asserts `== 2`
  (RED pre-fix), `_post_approval_protected_changes` flips it to DENY (GREEN); degrade
  case proves allow+WARN parity with today's guard.
- Date:

## Sharp-edge entry to add
None new — this **retires** an existing SHARP_EDGES residual note rather than adding a
footgun. The durable lesson (a documented "deferred to post-vX" residue with only a
human mitigation is orphaned forward-intent that no tracker was reading until the
orphan-intent net surfaced it) is a process observation for the session log, not a
new code footgun. If a footgun *does* emerge during execution, it is most likely the
GitHub-API-dependency shape: a previously offline-pure gate now degrades silently to
the manual mitigation when a token scope is wrong or the API rate-limits — worth a
one-line SHARP_EDGES note *only if* the degrade path proves confusing in practice.
