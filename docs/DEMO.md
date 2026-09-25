# Espalier-Harness Demo

A 5-minute walkthrough showing what Espalier-Harness does in practice.

## What this demo proves

- A **risky action is locally flagged or blocked** (write_guard hook on
  a Write to a protected harness path).
- A **repo-condition readout** surfaces what the harness sees on disk
  (`espalier doctor`).
- The **release/CI check** is the final merge-time gate
  (`scripts/release_check.py`).

## What this demo does NOT prove

- That Espalier-Harness **cannot be circumvented**. It can — see
  [`SECURITY.md`](../SECURITY.md) and [`SHARP_EDGES.md`](SHARP_EDGES.md)
  for the documented bypass classes (two-step subprocess, command
  substitution variable forms, `disableAllHooks: true` set before
  Claude Code launches).
- That Espalier-Harness is a sandbox. It is not. Local hooks run in the same
  trust domain as the agent.
- That the demo's specific scenario covers the full bypass-class corpus.
  See [`bench/RESULTS.md`](../bench/RESULTS.md) for the regression
  corpus and per-baseline block counts.

The honest one-line claim: espalier makes bypass attempts **visible,
testable, and harder to merge unnoticed**. That's it.

## Setup

```bash
# Clone and install
git clone https://github.com/Mike-Byrne-AI/espalier-harness.git
cd espalier-harness
python -m venv .venv
. .venv/bin/activate          # PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -e .

# Verify install
espalier --version
```

Expected (exact version varies per release — anything in the `0.8.x`
prerelease line is fine):

```
espalier 0.8.0a10
```

## Beat 1 — Local hook flags a risky write

The friction layer denies a Write tool call that targets a protected
harness path. We invoke the hook directly with a sample tool-call
payload — Claude Code does the same thing on every PreToolUse event.

```bash
echo '{"tool_name":"Write","tool_input":{"file_path":"tools/cc/hooks/demo_target.py"}}' \
  | python tools/cc/hooks/write_guard.py
echo "exit=$?"
```

Expected (`exit 0` plus structured JSON on stdout; the `permissionDecisionReason`
is quoted in full below, nothing elided — a test compares it to the live hook
clause by clause):

```
{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "Write to protected harness zone blocked: tools/cc/hooks/demo_target.py. Harness self-edits: exit and relaunch with `ESPALIER_MAINTENANCE_MODE=1 claude --continue` (env read at launch; mid-session export is ignored; --continue keeps this session). Do NOT disable hooks to proceed -- that loosens future safety.\n  Don't: edit harness files from a regular session (`.claude/settings.json`, the whole `tools/cc/` tree, etc.), and don't disable hooks to get around this.\n  Do: ask the operator to relaunch with `ESPALIER_MAINTENANCE_MODE=1 claude --continue` BEFORE the edit (env-vars set mid-session don't reach already-running hooks; --continue keeps the session you are in), then resume the change through your normal workflow (/implement-task) -- the harness self-edit is the exception, not your task.\n  Your own source colliding with a harness path (e.g. a top-level `cc/`)? Relocate it from your own terminal, outside a Claude Code session (the guard reads tool calls, not your shell) -- maintenance mode is not the remedy for that."}}
exit=0
```

> Run this with `ESPALIER_MAINTENANCE_MODE` unset — when the env var is set
> (harness self-edit mode) the protected-zone check is bypassed and the hook
> returns `exit 0` with no deny.

What just happened: the agent attempted to overwrite a hook script.
`write_guard.py` matched `tools/cc/hooks/` against `PROTECTED_PREFIXES`
and denied the call before the file system saw it. The deny *reason*
flows back to Claude Code via the `permissionDecisionReason` field —
the agent gets a useful error instead of a silent failure.

This is **friction**, not a sandbox. A user with local filesystem
control can disable the hook before launching Claude Code (see
[`SHARP_EDGES.md`](SHARP_EDGES.md) "Local Hooks Are Not a Sandbox").
That's why the next two beats exist.

## Beat 2 — Repo-condition readout

```bash
espalier doctor .
```

Expected (truncated to the first ~25 lines for the demo; the full output is
JSON with keys sorted alphabetically, so `checks` leads):

```
{
  "checks": {
    "audit": {
      "status": "pass"
    },
    "diff": {
      "build_plan_changed": true,
      "fingerprint_changed": true,
      "status": "warn"
    },
    "presence": {
      "missing_paths": [],
      "partial": false,
      "present_paths": [
        "cc/COMMANDS.md",
        "cc/LIVE_SURFACE.md",
        "cc/PACK_MANIFEST.txt",
        ".claude/settings.json",
        "reports/repo_fingerprint.json",
        "reports/harness_config.json"
      ],
      "required": [
        ...
```

What just happened: doctor compared the on-disk managed-paths inventory
against the saved harness plan and the integrity manifest. It exits 0
on `pass`/`warn` and non-zero on `fail`. `warn` is the typical state
when a managed file has been added or removed since the plan was last
regenerated — actionable but not blocking.

The output is intentionally JSON: doctor is meant to be both
human-skimmable and machine-parseable (CI consumes the same output).

## Beat 3 — Release / CI gate

```bash
python scripts/release_check.py
```

Expected (last lines — a per-check PASS/SKIP table, then a summary):

```
license_present              PASS
security_present             PASS
contributing_present         PASS
changelog_present            PASS
canonical_urls               SKIP   opt-in publish-time gate; set ESPALIER_RELEASE_CHECK_WITH_URLS=1 to verify ...
tests_pass                   SKIP   set ESPALIER_RELEASE_CHECK_WITH_TESTS=1 to run
wheel_smoke                  SKIP   release CI runs scripts/wheel_smoke.py per matrix cell; ...

19 passed, 3 skipped (set ESPALIER_RELEASE_CHECK_WITH_TESTS=1 and ESPALIER_RELEASE_CHECK_WITH_WHEEL_SMOKE=1 for full ladder).
release_check OK
```

What just happened: `release_check.py` invoked the cleanliness gate
(`espalier.pre_release.run_cleanliness_gate`) — the same code the
release CI workflow runs. Hard failures (placeholder contacts, public
vulnerability-routing language in SECURITY.md, internal-material leaks,
missing required public files) cause the script to exit non-zero;
release CI then fails the build. Transient warnings (build caches,
`__pycache__`) are surfaced but not blocking.

Local hooks added friction. Doctor surfaced the local condition.
**This** is the merge-time gate — running on a runner outside the
agent's reach.

## Why this ordering matters

| Beat | Layer | Where it runs | What it actually does |
|---|---|---|---|
| 1 — write_guard | Friction | Locally, in Claude Code | Raises the cost of casual mistakes |
| 2 — doctor | Visibility | Locally, on demand | Surfaces what's on disk vs what should be |
| 3 — release_check | Guarantee | CI, outside the agent | Gates merges; the only real boundary |

If you remove the third layer, what's left is a tool that catches
sloppy edits and surfaces drift. That's still useful — but **CI plus
branch protection is where the real boundary lives**. Espalier-Harness
exists to make all three layers pull their own weight, not to pretend
the local layers are more than they are.

## Optional: record this flow as a short GIF before launch

The recording materials live under [`bench/demo/`](../bench/demo/) —
`script.md`, `RECORDING.md`, `TROUBLESHOOTING.md`. Recording is not a
release gate; the placeholder reference in README is fine for first
release.

## Receipts

Everything in this demo is testable in the repository:

- `tests/test_demo_end_to_end.py` runs each beat as a subprocess and
  verifies its output shape — drift here will fail CI.
- The friction layer's catalog of in-scope and out-of-scope cases is
  pinned in `tests/test_write_guard.py::TestBashDocumentedOutOfScopeBypasses`.
- The cleanliness-gate failure paths are pinned in
  `tests/test_pre_release.py::TestSecurityPolicyGate` and the
  Pack 3 internal-leak class.
