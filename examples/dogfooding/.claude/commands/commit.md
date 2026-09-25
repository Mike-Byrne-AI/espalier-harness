Review uncommitted changes, then stage and commit with a generated message.

## Step 1: Overview
```bash
git diff --stat
```

## Step 2: Detailed review
```bash
git diff
```

For each changed file:
1. **Summarize** the change in one sentence
2. **Risk check:**
   - Does it touch harness files (`tools/cc/`, `.claude/`, `espalier/`)?
     If yes, verify the change is intentional.
   - Does it touch files warned about in docs/SHARP_EDGES.md?
   - Does it introduce new dependencies or change existing ones?
3. **Convention check:** Does the change follow docs/CONVENTIONS.md?

## Step 3: Generate commit message
```
<type>(<scope>): <description>

<body — what changed and why>
```
Types: feat, fix, refactor, test, docs, chore, style
Scope: the module or area affected

Present the message and wait for approval.

## Step 4: Commit

First, the **pre-commit provenance gate** — the ~1s CLI twin of the full-suite
`test_no_provenance_in_shipped_code`. It catches an internal build-history tag
(`TP-NNN`, `round-N`, `wf_…`) that slipped onto a shipping surface — e.g. a
`tools/cc/` comment that byte-mirrors into the shipped `espalier/_vendor/cc/` —
BEFORE the commit, not after (avoids the commit → full-suite-red → re-commit cycle):

```bash
python -m espalier provenance .
```

Exit 0 = clean, proceed. Exit 2 = offenders: strip the provenance wrapper (keep
the behavioral content) or add a load-bearing entry to `_ALLOWED_HITS` with a
reason, then re-run. Do NOT stage until it exits 0.

On any repo other than the Espalier-Harness source tree this census stands down
and prints why, exiting 0. That is expected, not a misconfiguration: it polices
Espalier's own internal build-history vocabulary (`TP-`, `TQ-`, `XPLAT-`), which
overlaps ordinary ticket prefixes, and its remedy lives in a constant inside the
installed engine that you cannot edit.

```bash
git add -A
git commit -m "<approved message>"
```

Report the commit hash. On the Espalier-Harness source tree, run the cheap
arms of the landing check now — trailer, owed-list probes and candidate keys,
all sub-second — and skip its test slice:
```bash
if [ -f scripts/check_handoff_landing.py ]; then
  python scripts/check_handoff_landing.py --skip-tests
fi
```
The full landing check (its ~70 s test slice is session-scoped, not
commit-scoped — it re-runs the same growing set every time) belongs to
`/handoff` step 7c, once. Running the whole gate after each commit paid
that slice three times in one session (2026-09-06) for checks that take
under a second. An adopter repo has no `scripts/` and skips this.

## Step 5: Offer to ship *(ask first — never automatic)*

After a clean commit, **offer** (do not perform unprompted):

- If on the default branch (`main`/`master`), branch first.
- Push the branch.
- Open a PR with `gh pr create`, drawing the body from the commit chain and
  the session blueprint's `reasoning_entries`
  (`kind=decision|alternative|pattern|insight`).

Only proceed on the user's explicit yes (global rule: commit or push only
when asked; branch first when on the default branch). If the user declines,
stop here — nothing is pushed.

---

Session work done? Run `/handoff` to persist reasoning + the MEMORY row
before you close.
