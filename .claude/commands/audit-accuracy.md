---
description: Run the accuracy audit and walk through any failures.
---

# /audit-accuracy

Run Espalier-Harness's accuracy audit on the current repo and report findings.
Layer 1 of the verification stack — mechanical (no LLM cost) by default.

## Steps

1. Run the audit and capture JSON to a temp location (never the repo root —
   the file is not gitignored and would otherwise show up as untracked every
   run). Compute the OS temp dir, then write there:

```bash
OUT="$(python -c 'import os,tempfile; print(os.path.join(tempfile.gettempdir(), "cc_audit.json"))')"
python -m espalier audit-accuracy --no-llm --json --only-failing > "$OUT"
```

2. Parse the `cc_audit.json` written to `$OUT`. If `claims_failed == 0` and
   `claims_total > 0`, report success and exit:

   > Accuracy audit clean: N claims verified, no failures.
   > (M unverifiable claims skipped — LLM dispatch not configured.)

3. If `claims_failed > 0`, walk through each failed claim:

   - Quote the **claim text** and **location** (`file:line`).
   - Quote the **evidence** field.
   - If `verification_mode == "live_repo"`: propose a doc edit to match
     reality. Example wording:

     > Change the stale count in `CLAUDE.md` to match the live count
     > in `tools/cc/hooks/`.

   - If `verification_mode == "external_pin"`: do **not** propose an
     edit unilaterally. Pinned-external drift is a human decision —
     either the pin is stale (refresh via `espalier refresh-externals`)
     or the project doc misread the contract. Surface the contradiction
     and ask the user which side to update.

4. Do not modify any files without explicit user approval.

## Constraints

- **Layer mandate.** This audit verifies Espalier-Harness's own documented
  claims against either live repo state or pinned external excerpts in
  `docs/external/`. It does **not** perform a general code review and
  does **not** verify claims by quoting other project docs.
- **Mode selection.** `--no-llm` is the default. The mechanical
  verifiers cover every numerical / count claim. Claims about external
  contracts (hook protocol, schema fields) are reported as
  `unverifiable` until an LLM verifier is plugged in via the
  `LLMDispatch` callable contract in the engine's `audit_accuracy` module. No
  agent ships today; the contract is open for future wiring. That's
  honest — the auditor only claims what it can verify.
- **Exit semantics.** The CLI exits `1` when any claim FAILs, so this
  command is safe to chain with `&&` to gate further actions.
- **Out of scope.** This command does not auto-fix failures. Surfacing
  drift is the value; resolving it is operator judgment.

## When to invoke

- Pre-release: as part of the release-readiness walk-through.
- Post-doc-edit: any session that touched `README.md`, `CLAUDE.md`,
  `docs/SHARP_EDGES.md`, or `.claude/skills/*/SKILL.md`.
- Routine: weekly, paired with `/scan` and `/preflight`.
