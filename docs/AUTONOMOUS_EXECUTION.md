# Autonomous Execution — the loop-over-`claude -p` driver

**Audience:** contributors / maintainers running the harness unattended.
**Status:** the driver (`scripts/run_pack_chain.sh`) is **dev-only** — it lives in
`scripts/`, is not packaged (`[tool.setuptools.packages.find] include =
["espalier*"]`), and never reaches an adopter wheel/sdist. It is, however,
subject to the shipping-surface contracts that scan `scripts/`.

This doc records *why* the driver works and the failure modes it surfaced, so the
next operator does not re-derive them the hard way. It is descriptive, not a
feature promise.

---

## 1. What it is

`run_pack_chain.sh` runs each task pack as its **own fresh `claude -p` session**.
A one-shot `-p` invocation is a complete, headless Claude Code session: it fires
the same SessionStart/Stop hooks an interactive session does, then exits.

The driver automates the manual session-boundary cycle a human runs between
packs:

| Manual step | In the loop-over-`-p` |
|---|---|
| `/handoff` (write docs + blueprint to disk) | end of each `claude -p` (the Stop gate auto-finalizes the blueprint) |
| `/clear` / new window | the **next** `claude -p` invocation — the process boundary *is* the clear |
| context re-hydrate (was a manual `/context-load`) | start of each `claude -p` — **automatic**: the SessionStart hook injects the on-disk baton before the model's first turn (no `/context-load` call; that command is now only for explicit mid-session re-orient, PostCompact, or DEGRADED recovery) |
| "the objective continues" | the outer `for pack in "$@"` loop hands the next pack to the next invocation |

**The on-disk blueprint + MEMORY is the only baton that crosses the session
boundary.** Fresh context per pack is the token saving; the disk is the carrier.
This works because the harness's SessionStart/Stop hooks already *are* the
context-load/handoff, and they fire on Claude Code *events*, not on whether a
human is watching.

**The goal invokes the real command — it is not a paraphrase.** The `-p` prompt
runs the actual `/implement-pack <pack>` slash command (headless `-p` expands a
leading-slash prompt into the real command body), so the *whole* workflow executes,
not a named subset. This matters *because* the driver runs in
`ESPALIER_MAINTENANCE_MODE`, which bypasses the `plan_guard` + `stop_gate`
backstops (and `write_guard`'s protected zones and `subagent_stop`'s blueprint
append with them): with the hook backstops off, the goal is the only thing carrying the
workflow, and the only faithful way to carry all of it is to run the command
itself (a paraphrased subset silently drops the steps it fails to name — the root
cause of the first run's mechanically-green-but-incomplete packs). The session also
writes one `cc/_pack_receipt.json` (red-team + 0-A + suite counts) the driver
verifies — see §4.

---

## 2. Verified facts about `claude -p`

Tagged by how they were established. "Verified" = confirmed via a hook
side-effect (a flag mtime, a new blueprint file), not just model stdout.

- **SessionStart fires in `-p`.** *(verified)* — the `session_started` flag mtime
  advanced and a new per-session blueprint appeared.
- **The SessionStart hook auto-injects the disk baton in `-p`.** *(verified)* — a
  zero-history `-p` reported a prior session's depth + last-pack fact that exists
  *only on disk*, orienting entirely from the baton with **no `/context-load`
  call** (context-load is now only for explicit mid-session re-orient, PostCompact,
  or DEGRADED recovery — so the driver's goal text no longer opens with it).
- **`claude -p` is a fresh context per invocation.** *(verified by construction —
  the process boundary.)*
- **Stop / blueprint-finalize fires in `-p`.** *(probable)* — the latest-blueprint
  pointer updated at session end and the pilots self-committed; inferred from
  side-effects, not from the hook spec. If Stop did *not* fire, the auto-finalize
  baton would silently not persist — worth a one-line confirm against the Claude
  Code hook docs before relying on it.
- **`/clear` clears an active `/goal`.** *(verified)* — so you would never `/clear`
  mid-chain; the next `-p` is already fresh.

---

## 3. The staged channel-probe discipline

Before running a real pack through a new automation channel, **probe the channel
read-only first** — and read the *hook side-effects*, not stdout:

1. Does a nested `claude -p` even run from here? (auth / network / process —
   return a sentinel, check the exit code.)
2. Does the SessionStart hook *fire* in `-p`? (watch the `session_started` flag
   mtime + the blueprint store — **not** stdout, which can be empty while the
   hook ran.)
3. Does the SessionStart hook load the baton into the `-p` turn? (the `-p` should
   echo a fact that exists only on disk — automatic, no `/context-load` call.)

The trap: the first probe returned a success sentinel but the blueprint files did
not change, so you could not yet tell whether SessionStart had fired. Stdout
success is not hook-fired evidence — the decisive test reads the side-effect.
This is the untrusted-oracle discipline applied to channel bring-up.

---

## 4. Driver safety design (the non-negotiables in `-p`)

- **Halt-on-failure between packs.** In `-p` there is no human to triage, so the
  chain never builds pack N+1 on a broken pack N (`exit 1` on any halt).
- **Fail-fast chain preflight.** Before the first `-p` spends a cent, every named
  pack is validated — it resolves to exactly one file and is pack-shaped (carries
  a `## Landing` `State:` line). A typo'd or malformed pack named 5th fails *now*,
  not after packs 1-4 already spent budget.
- **Dispatch sentinel (before the first pack).** The whole pipeline rests on the
  `-p` goal *invoking* the real `/implement-pack` command (headless `-p` expands a
  leading-slash prompt into the command body). Before any pack spends budget, the
  driver probes the exact production shape — `claude -p "Run the real slash command:
  /status"` — and **halts the chain** if the slash did not dispatch (no `/status`
  banner token in the output). So a CC version or machine where headless
  slash-expansion is unavailable fails loudly at startup instead of silently
  degrading every goal to a prose paraphrase — which the receipt gate would *not*
  catch, since a prose-degraded session still writes a receipt claiming it ran.
  Skipped in `--dry-run` (no real `-p`); opt-out seam
  `PACK_CHAIN_SKIP_DISPATCH_SENTINEL=1`.
  *Emission ≠ dispatch (residual limit):* the halt is keyed on token-**presence**
  — `grep -F "SURFACE:"` against the probe's combined stdout+stderr — not a
  structural dispatch witness the bash body cannot fake. It proves the distinctive
  banner token was *emitted* (strong evidence a real `/status` ran), but a
  prose-degraded session that reproduced the banner shape would still false-pass.
  Treat it as a high-signal heuristic against silent slash-expansion loss, not a
  proof of dispatch; its strength rests on the token's distinctiveness (all-caps
  `SURFACE:`, not the pervasive lowercase "surface").
- **Ambiguous-token halt (collision guard).** A pack token that matches more than
  one file **halts** with the full match list — it never silently runs one and
  drops the rest (the earlier `matches[0]` behavior).
- **Independent scope gate, pre-`-p` (advisory).** Before spending budget,
  `espalier scope-check` runs against the pack and its actionable undeclared
  references are folded into the goal so the session widens the pack's declared
  scope. The gate **never halts on scope** — scope-check is officially a signal,
  not a gate, and its severity signals are too noisy for an automated halt: a raw
  gap-*count* trips on a common affected-symbol token (`.gitignore` matches
  hundreds of files that merely mention it), and the `[HIGH-RISK]` guarded tag
  trips on an ordinary symbol name like `main` (which token-matches the "Main
  session" surface). A config-only pack that declares no affected symbols simply
  skips the gate — as `/implement-pack`'s own 0-B does. A genuinely major scope
  problem is caught downstream — by the `-p` session's own `/implement-pack` 0-A
  review and the commit / red-team / install gates — not by a noise-prone
  pre-`-p` mechanical halt.
- **Independent post-`-p` commit verification.** Don't trust the goal's
  self-report — `HEAD` must actually have advanced (a new commit made) before
  advancing to the next pack. Verification is by HEAD-advance, **not** by grepping
  the commit message for the pack ID: this repo's convention forbids pack IDs in
  commit messages, so a token-grep would false-halt after every correctly-messaged
  commit.
- **Single pack receipt (required).** Every session writes one
  `cc/_pack_receipt.json` (red-team + 0-A pack-review + suite counts, even at zero).
  Its **absence halts the chain** — closing the old "skipped == clean" gap: the
  driver can no longer confuse "red-teamed, found nothing" with "skipped the pass."
  It also halts on a skipped red-team or a skipped 0-A (`red_team.ran` /
  `pack_review.ran` false). A receipt claiming blockers still requires re-runnable
  repros the driver **independently re-runs** (`espalier.red_team_guard`); a
  non-reproducing blocker halts the chain, as does one whose `match` the guard
  refuses before running it (a catch-all, or a pattern one character satisfies;
  the halt report names which). The `commit` / `changelog_touched` /
  `suite` fields are advisory cross-checks (the suite count is transcribed —
  session-attested — into the Landing stanza; the driver never fabricates one).
- **Driver-owned move-to-`Done/` + Landing finalize.** After the gates pass, the
  driver itself moves the pack to `Done/` and stamps its `## Landing` stanza
  (`State: LANDED` + `Commits` + `Date` + the receipt's session-attested `Suite`),
  completing the step the session may have skipped. This reverses an earlier "rely
  on the session for landing hygiene" decision — the first unattended run showed
  only 1/9 sessions performed the move; deterministic bash is the reliable owner. It
  stamps only mechanically-known fields and labels `Suite` provenance; it never
  invents a suite number it did not receive.
- **Independent install-green gate** (`verify_install_green`, see §5).
- **Local-only commits.** Nothing is ever pushed (no remote step exists).
- **`ESPALIER_MAINTENANCE_MODE` exported in the *parent* shell** so every nested
  session inherits it — never inline (a mid-session `export` doesn't reach an
  already-running hook; an inline-prefixed `git commit` is denied wholesale).
- **Per-pack budget cap is OPT-IN** (`--budget N` → `claude --max-budget-usd`).
  By default there is **no** dollar cap, so a long but productive pack is never
  killed mid-way (a cap cut-off would read as a halt and lose the work). Runaway is
  bounded instead by the turn instruction in the goal text, the halt-on-failure
  between packs, and the operator (the run is killable). On a Claude subscription
  there is no per-token dollar billing anyway — the real limit is the subscription
  usage window, which no CLI flag governs.
- **`--permission-mode auto`** so no per-tool prompt stalls an unattended run.
- **`--dry-run`** prints the exact invocation + expanded goal (and runs the
  cheap pre-`-p` gates: preflight + scope gate) but fires no `claude -p`.
- **Resume ledger + committed-but-ungated marker.** Each pack that clears the
  full post-`-p` verify is appended to `cc/_pack_chain_ledger.txt`; a re-invoke
  skips packs already in it, so a mid-chain halt → fix → re-invoke only re-runs
  the unfinished tail. Separately, the driver records a pack's commit in
  `cc/_pack_chain_committed.txt` **the instant HEAD advances — before the
  post-commit gates**. So if a *post-commit* gate halts (a transient install-green
  flake) or the session is killed mid-verify, the commit is already in git but the
  pack is un-ledgered; a plain re-invoke detects the marker and re-runs **only the
  post-commit gates** against that commit, rather than re-executing the session
  (which, the work already committed, would make no new commit and false-halt as
  `HALTED-nocommit`). The re-gate is fail-closed toward the commit's identity: it
  refuses (`HALTED-regate`) if the recorded commit is no longer an ancestor of HEAD
  (its work was reset/rebased away), and the receipt gate refuses a receipt left by
  a *different* pack (`receipt.pack` mismatch) — so the resume never green-washes a
  pack against unrelated proof. **Footgun:** `--fresh` clears *both* the ledger and
  the committed marker, so a `--fresh` re-invoke of a chain with a committed-but-ungated
  pack re-runs its session and false-halts on nocommit — reset that commit or
  re-gate it by hand before a `--fresh` re-run.
- **Per-pack run report.** After the loop (or on any halt — it prints via an EXIT
  trap) a table shows each pack's outcome (`LANDED` / `SKIPPED-resumed` /
  `HALTED-*`), the verified commit short-SHA, and wall-clock seconds.

---

## 5. The install-green gate

`verify_install_green` runs after the commit-verify and red-team-verify (cheap
checks first; this one is heavy). It builds a throwaway venv **under `mktemp`**
(outside the worktree — never an `rm -rf` of an operator dir, never pollutes `git
status`), `pip install`s the committed tree, runs the repo's install-green
oracle, and cleans up — so "green" is CI-equivalent by construction, not
dev-shell-relative.

**What it checks, honestly:**

- `pip install . pytest` **succeeds** — catches build / packaging / dependency
  regressions (a missing package-data glob, a broken `pyproject`). It installs
  the **minimal closure** the oracle actually exercises (the package + `pytest`),
  not the full `[dev]` extra, and uses `--retries/--timeout` so a transient
  PyPI/DNS blip does not false-halt a long unattended chain (a pip failure is
  reported as "flake OR packaging regression", not as env-relative green).
- `espalier selfcheck` is **green against the INSTALLED package** — it resolves
  its bundled mirror from site-packages via `importlib.resources` and is run from
  a *foreign cwd*, so `import espalier` cannot fall back to `./espalier`.

**What it deliberately does NOT do:** re-run the full pytest suite in the venv.
That would be **theater** here — `pyproject.toml` sets `pythonpath = ["."]`, which
puts the source tree on `sys.path` for every run, so the full suite passes *even
with the package uninstalled*. The `selfcheck` channel is the repo's purpose-built
"run curated tests against the installed engine without the repo tree" mechanism;
it is the real install-green check.

Opt out with `PACK_CHAIN_SKIP_INSTALL_GATE=1` for fast iteration; the gate is on
by default for unattended runs.

---

## 6. Failure modes this surfaced

Each has a full entry in `docs/FAILURE_MODES.md`; the operator-facing footgun
form is in `docs/SHARP_EDGES.md`.

- **A — The one-shot deferred-gate stall** (FAILURE_MODES §7.9). A one-shot `-p`
  has no loop to resume into; the moment it backgrounds a gate and yields, the
  session exits 0 with the work uncommitted. Mitigation: run every gate
  synchronously/foreground inline and carry through to the commit in one
  continuous run; the driver's commit-verify catches the symptom.
- **B — `pipefail` + `grep -q` SIGPIPE race** (FAILURE_MODES §7.6). `grep -q`
  closes the pipe on first match while the producer is still writing → SIGPIPE →
  `pipefail` false-fails. Mitigation: capture-then-grep via a here-string.
- **C — Env-relative autonomous "green"** (FAILURE_MODES §9.4). A stale editable
  install makes "green" PYTHONPATH-green, not install-green. Mitigation: the
  install-green gate (§5).
- **D — A new shipping-surface file commits before the full provenance suite
  gates it.** The driver commit itself once shipped a provenance tag in its
  usage-example comments because a keyword contract slice ran instead of the full
  suite; it was caught by the *next* pack's autonomous full-suite run and fixed in
  a separate commit. Mitigation: `git add` first and run the full suite (or the
  targeted `test_contracts` + provenance runs) before committing any new tracked
  file; use placeholder example args.

---

## 7. Not yet verified (don't state as fact)

- Whether the Stop *event* fires in `-p` per the hook spec (vs only as observed
  via side-effects) — §2.
- The fabricated-blocker halt path end-to-end *in a live run*: the red-team guard's
  *bite* is proven by its own tests, and the driver's receipt-gate tests exercise
  the missing-receipt / skipped-step / non-reproducing-blocker halts against a
  mocked `claude` — but no real unattended `-p` run has yet tripped a genuine
  fabricated blocker.
- Whether `--permission-mode auto` + the budget cap bound *every* stall surface
  (only the deferred-gate stall was observed; network hangs / uncovered prompts
  are unprobed).
- **Platform-premise durability (partially closed).** Slash-command dispatch and
  foreground-subagent dispatch in `-p` are doc-verified (§2). The *startup* dispatch
  regression is now caught mechanically: the dispatch sentinel (§4) probes the real
  slash shape before the first pack and halts the chain if it does not dispatch, so a
  CC downgrade or a machine without headless slash-expansion fails loudly instead of
  silently degrading every goal to prose. What remains open is a *mid-run*
  degradation that still self-attests — the receipt gate catches a *missing* receipt
  but not a run that degraded *after* the sentinel passed yet wrote a receipt claiming
  it ran; and foreground-subagent dispatch is still re-checked only by the manual
  probe. Re-run the probe after any CC upgrade. The 2026-10-14 channel probes (§8)
  re-ran both by hand on two machines: they sent a bare `/status`, not the
  sentinel's prose-prefixed form, and found the dispatch in the session transcript,
  not in the output the sentinel reads.

---

## 8. Channel probes on both machines (2026-10-14)

Nine probes of `claude -p` ran on the Mac seat (macOS, Claude Code 2.1.296) and on
the Windows seat (Windows 11, Claude Code 2.1.299), each in a throwaway worktree of
that machine's clone, never a seat's own tree. Every run used `--output-format
stream-json --verbose` with its stream saved, a wall clock that killed the whole
process tree, and UTF-8 decoding. `CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT`,
`CLAUDE_PROJECT_DIR` and `ESPALIER_MAINTENANCE_MODE` were stripped (the Windows seat
stripped every `CLAUDE*` and `ESPALIER_*` variable), so maintenance mode was off
except in one stall probe that set it on purpose; unlike the driver in §1, which runs
with it on. The Mac ran under `--permission-mode bypassPermissions` except the stall
probe, which ran under `auto`; Windows ran every probe under `auto`, with `--model
opus` because that box defaults to another model. The oracle was the saved stream,
the session's transcript or the filesystem, never a token the model printed. The
probe-by-probe record (each prompt, version, stream path and result) is under the
`### W0 results` heading of the seat runner's plan in `task-packs/`; the Windows rows
are that seat's own report. *Verified* below means observed in a saved stream,
transcript or file on both machines.

- **A headless session runs and its hooks fire.** *(verified)* A one-word prompt
  ended with a `result` event and exit 0 (11.6 s, 15.8 s); during the run the session
  marker appeared under `.espalier-state/sessions/` and the blueprint store moved —
  side-effect evidence of the kind §2 used, now on Windows too.
- **A slash command dispatches, and the transcript is the place to see it.**
  *(verified by the transcript; the stream itself shows no expansion)* The probes
  sent a bare `/status`; the driver's sentinel and goals send a prose-prefixed form
  (`Run the real slash command: /status`), which they did not try. The stream-json
  output does not echo the expanded command; the
  persisted transcript (`~/.claude/projects/<slug>/<session id>.jsonl`, the id from
  the stream's `init` event) carries the command-name tag and the command body, and
  the session ran the body's commands verbatim. A runner that checks dispatch reads
  the transcript, so session persistence stays on. Two cautions for the §4 sentinel,
  which reads a banner token in the output: that token is model-printed text, and on
  Windows one run's `/status` argument was rewritten by Git Bash's MSYS path
  conversion into `C:/Program Files/Git/status` while the model still called the
  `status` skill. So a skill call is no proof of dispatch either, and a slash goal is
  never passed through an MSYS argv.
- **A foreground subagent runs.** *(verified)* An `Agent` call of the requested type
  and its hand-back appear in the stream; a one-word subagent cost about 43-44k
  tokens on each machine. Where the reply lands differed by version (the call's
  `tool_result` on 2.1.296, a hand-back event's input on 2.1.299), so a runner
  records `claude --version` beside every stream.
- **The dispatch tools work inside `-p`.** *(verified)* `tools/cc/mail.py
  assignments` and `tools/cc/board.py` ran as tool calls and their JSON parsed.
- **No step stalled under `--permission-mode auto`** for an edit under `tools/cc/`, a
  commit on a scratch branch and `gh pr list`. *(verified, for those surfaces only)*
  Without maintenance mode `write_guard` refused the edit — the harness's guard, not a
  permission prompt — and the refusal is also data in the `result` event's
  `permission_denials`; with it, every step ran. This narrows §7's open question; it
  does not close it.
- **The `result` event does not end a session; the process exiting does.**
  *(verified)* A session that backgrounds a long command emits a `result` while the
  command still runs, stays up, and emits another `result` carrying the output when
  the background task finishes. A runner reads the **last** `result` after the
  process exits. A kill of the whole process tree at the bound left no survivor on
  either machine. This refines §6's deferred-gate stall: on these versions the process
  did not exit at the first `result`.
- **A full proof tier inside `-p` runs in the background, not the foreground.**
  *(verified)* On both machines the session backgrounded the tier itself. On the Mac
  it finished in 29.9 minutes and the process exited on its own; on Windows the
  75-minute bound killed it at 89 percent of the parallel leg, with another pytest on
  the box. Design input: the runner, not the session, runs the tier, under a bound
  no probe has measured yet, since the Windows run never finished. On the Mac
  `claude` exited 0 while the tier was red (two failures, two errors), so the verdict
  is the tier's own receipt, never the session's exit code.
- **A headless `/implement-task` approves its own plan.** *(verified)* On both
  machines the session created the plan and went on to the edit without presenting
  the plan or asking anything, so the step that waits for an approval is skipped
  silently in `-p` (one run on each machine). A runner cannot take that approval
  from the session; whether any headless form of the procedure keeps it is open.
- **The banner's `Sessions:` line counts ended `-p` sessions as live siblings.**
  *(verified)* After the probes, the next banner listed every finished and killed
  `-p` session; a runner checks process ids itself before refusing to start beside
  another session.
