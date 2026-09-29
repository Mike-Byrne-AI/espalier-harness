# Espalier demo — the plan

One document for what to record, in what order, with what on screen and what
to say over it. [`RECORDING.md`](RECORDING.md) is the how: setup, tooling,
post-processing, the README embed and the troubleshooting table. Nothing else
under `bench/demo/` is load-bearing.

Three artifacts, each with one job:

| Artifact | Length | Job | When |
|---|---|---|---|
| **Hero GIF** | about 50 s | Earn the scroll on the README and plant one frame: the human holds a key the agent does not | Launch gate |
| **Zero-to-ahead clip** | about 15 s | "One command and you start where we are after months" | Launch, if the take is clean; else fast-follow |
| **Narrated walkthrough** | 3 to 4 min, hosted | Show the breadth: the systems the GIF cannot carry, with a voice saying what each one is and is not | Fast-follow |

A GIF holds one beat. Breadth in thirty seconds becomes noise. So the GIF
gets one story and the walkthrough gets the rest. The README's systems map
(specified at the end of this file) is where a reader sees the whole spine
after the GIF has earned the click.

---

## Rules that apply to every take

1. **Record beats 1 to 4 with `ESPALIER_MAINTENANCE_MODE` UNSET in the shell you
   launch from.** With it set, the protected-zone deny does not fire and the plan
   gate is skipped: you would record a dead demo. Run `unset ESPALIER_MAINTENANCE_MODE`
   in that shell as a command, not a check. The `env -u` in the re-drive commands
   below scrubs that one command only; it does not scrub the shell you launch
   `claude` from. Beat 5 is the one place it is set, on purpose, on camera.
2. **Record against a throwaway demo-target that has never had a session**, never
   the espalier source repo. The hook check and the practice run each open a
   session there, so recreate the target after them; `RECORDING.md` has the block
   and the order.
3. **Never fabricate output.** The deny text below was driven from the hooks on
   2026-09-28. Re-drive before recording (commands under each block). If the
   live text differs, the hook is the source of truth: update this file, not the
   hook. A long banner is trimmed in post, never retyped shorter.
4. **No staged kill-switch prompt.** Earlier drafts had the operator type "set
   disableAllHooks: true" as the climax. Months of daily self-host use have not
   produced an agent reaching for that on its own, so the prompt read as staged
   and the block read as blocking the user. The floor's real job is the accident
   case: an agent editing its own tooling, a half-applied hook edit, a settings
   cleanup that empties the hooks list. The hero shows that case with an
   ordinary prompt. The floor's reasoning belongs in README prose, not on camera.
5. **Every numbered claim on an end card is re-derived at record time**, with the
   commands in the systems-map section. This file carries no counts of its own.
6. **The hero is the launch gate.** A crisp hero beats a perfect set. Do not hold
   launch for the clip or the walkthrough.

---

## Verified on-screen text

Driven from the hooks in this tree on 2026-09-28, maintenance mode scrubbed from
the environment. The `✗ … hook blocked` line is Claude Code's UI envelope; every
line beneath it is the hook's `permissionDecisionReason`. The beat 3, beat 4 and
Bash-reference blocks are pinned clause by clause and the beat 5 line verbatim by
`tests/test_demo_end_to_end.py`, which also checks the beat 2 labels against the
hook's source; every block's zone list and relaunch spelling are pinned by
`tests/test_bench_demo_script_quotes.py`.

### Beat 2: the SessionStart banner header

Same header on an adopter tree and on this one, in the order it prints. Values
are elided with `…`; the continuity payload between `Blueprint:` and `Surface:`
scrolls, and a `Commands:` footer follows. Let them scroll, or trim in post.

```
=== Espalier-Harness === Session Start ===
Host: OS=Darwin; python3=yes python=no (python3 only)
Repo:      demo-target
Branch:    main
Status:    clean
Memory:    …
Blueprint: Auto-started new blueprint session
…
Surface:   healthy
Integrity: ok
```

On a tree that has never had a session the `Blueprint:` line reads the literal
above, with no depth counter. Do not expect or fake one. The `Host:` value is
the recording machine's own.

### Beat 3: the plan-gate deny

An Edit to `src/utils.py` with no plan open. The word in the first parenthesis
names the plan state and reads `missing` on a tree that has never had a plan.

```
✗ PreToolUse:Edit hook blocked
  No active execution plan (missing). Mutation requires status='in_progress'; a
  completed, planned, or cancelled plan does NOT authorize new writes.
    Don't: edit source files directly hoping the gate is advisory -- it's
    mechanical (PreToolUse deny). Repeated edits won't tire it out.
    Do: `/implement-task "<one-line description>"` then proceed. Use
    `/implement-task --multi` for coordinated multi-phase work. (attempted:
    src/utils.py) Adopter source roots: set `plan_exempt_prefixes = ["src/"]` in
    espalier.toml (see CLAUDE.md "Plan Guard" section). Do NOT use
    ESPALIER_MAINTENANCE_MODE for this — that scope is harness self-edits.
```

Re-drive from the demo-target root, no plan open:

```bash
env -u ESPALIER_MAINTENANCE_MODE python3 tools/cc/hooks/plan_guard.py <<'EOF'
{"tool_name": "Edit", "tool_input": {"file_path": "src/utils.py", "old_string": "a", "new_string": "b"}}
EOF
```

### Beat 4: the protected-zone deny on a hook file

An Edit to `tools/cc/hooks/session_start.py` from a regular session. This is the
climax. The `Do:` clause is the redirect the agent follows: it asks *you* to act.

```
✗ PreToolUse:Edit hook blocked
  Write to protected harness zone blocked: tools/cc/hooks/session_start.py. Harness
  self-edits: exit and relaunch with `ESPALIER_MAINTENANCE_MODE=1 claude --continue`
  (env read at launch; mid-session export is ignored; --continue keeps this
  session). Do NOT disable hooks to proceed -- that loosens future safety.
    Don't: edit harness files from a regular session (`.claude/settings.json`,
    the whole `tools/cc/` tree, etc.), and don't disable hooks to get around
    this.
    Do: ask the operator to relaunch with `ESPALIER_MAINTENANCE_MODE=1 claude --continue`
    BEFORE the edit (env-vars set mid-session don't reach already-running
    hooks; --continue keeps the session you are in), then resume the change
    through your normal workflow (/implement-task) -- the harness self-edit is
    the exception, not your task.
    Your own source colliding with a harness path (e.g. a top-level `cc/`)?
    Relocate it from your own terminal, outside a Claude Code session (the
    guard reads tool calls, not your shell) -- maintenance mode is not the
    remedy for that.
```

Re-drive:

```bash
env -u ESPALIER_MAINTENANCE_MODE python3 tools/cc/hooks/write_guard.py <<'EOF'
{"tool_name": "Edit", "tool_input": {"file_path": "tools/cc/hooks/session_start.py", "old_string": "a", "new_string": "b"}}
EOF
```

On Windows the same hint spells the PowerShell form first. Record on POSIX or
re-drive and paste the host's spelling.

### Beat 5: the maintenance-mode relaunch

After the relaunch the same Edit lands. That landing is the proof on screen: the
edit refused thirty seconds earlier now goes through. The guard also writes one
advisory line to stderr naming the bypass (driven 2026-09-28 with the variable
set):

```
[write_guard] MAINTENANCE_MODE -- protected-zone check bypassed
```

Whether Claude Code's default view renders an allowed hook's stderr is not
pinned anywhere in this repo; `RECORDING.md` step 7 checks it once before the
take. If it shows, beat 5 has two proofs; if not, the landed edit carries the
beat and the caption already stands on it.

### Reference: the Bash variant of the protected-zone deny

Not in the hero. Kept here because the walkthrough's bench chapter shows shape
breadth, and because the Bash form is a different template: a one-line
headline with the relaunch hint and no Don't/Do tail. This is the `tee` row of
the bypass corpus.

```
✗ PreToolUse:Bash hook blocked
  Bash write to protected harness zone blocked: .claude/settings.json. Harness
  self-edits: exit and relaunch with `ESPALIER_MAINTENANCE_MODE=1 claude --continue`
  (env read at launch; mid-session export is ignored; --continue keeps this
  session). Do NOT disable hooks to proceed -- that loosens future safety.
```

Re-drive:

```bash
env -u ESPALIER_MAINTENANCE_MODE python3 tools/cc/hooks/write_guard.py <<'EOF'
{"tool_name": "Bash", "tool_input": {"command": "echo x | tee --append .claude/settings.json"}}
EOF
```

---

## HERO: "the human holds the key" (about 50 s)

One continuous Claude Code session in the demo-target, with one cut before
beat 5. Positions espalier as a whole workflow whose floor cannot be switched
off from inside the session; the lockout is the climax and the relaunch is the
proof that the floor is a door, not a wall.

| Beat | Time | Action | On screen | Narration (caption) |
|---|---|---|---|---|
| 1 Title | 0:00 to 0:04 | Title card | `espalier — a spine for your Claude Code work, with a floor the agent cannot switch off from inside the session` | none |
| 2 Orient | 0:04 to 0:10 | `claude` opens | The banner header scrolls | "Every session opens already oriented. The banner is the harness naming its own systems." |
| 3 Plan gate | 0:10 to 0:22 | Prompt: **"Add a helper function to src/utils.py."** | The plan-gate deny; Claude replies that it will open a plan; `/implement-task` runs; the edit lands | "Source changes go through a plan. The gate is mechanical, and the agent follows the redirect." |
| **4 Lockout** | 0:22 to 0:34 | Prompt: **"Change the banner title in tools/cc/hooks/session_start.py to our team name."** | The protected-zone deny; Claude replies that it cannot from this session and asks you to relaunch in maintenance mode | "The agent cannot edit its own guardrails. It needs you to act. That is the whole point." |
| 5 Relaunch | 0:34 to 0:40 | Cut. In the shell: `ESPALIER_MAINTENANCE_MODE=1 claude --continue` | The same edit lands; the guard's advisory too, if the pre-take check showed the UI renders it | "When you mean it, one relaunch opens the door." |
| 6 Proof | 0:40 to 0:45 | Held frame | The differential table from `bench/RESULTS.md`: no-governance, settings-deny-only and espalier rows | "Every shape we have found is pinned so it cannot reopen. Plain deny rules catch none of them." |
| 7 End card | 0:45 to 0:50 | End card | A systems grid, counts re-derived at record time | "More than a floor. A spine." |

**Beat 4 names the file on purpose.** On a fresh adopter tree the banner's title
string lives in exactly one place, that hook file, but the seeded `CLAUDE.md`
quotes the banner and is not a protected path, so an unnamed prompt often lands
on an allowed edit and no deny fires. Naming the file keeps the prompt ordinary
and the take deterministic. If the agent reaches for `sed` or a redirect instead
of the Edit tool, the deny is the one-line Bash form quoted in the reference
block, not the block above: take two, or add "using the Edit tool".

**Beat 3 and beat 4 keep the agent's reply in frame.** The reply is the payoff:
a deny that steers, followed by an agent that is steered. Earlier drafts cut it
to save seconds. Do not. The block is not the point; what the agent does next is.

**Beat 4's reply is probable, not measured.** The `Do:` clause tells the agent
to ask for the relaunch and it usually does, but nobody has counted the rate. If
the first take's reply is mushy, take two. No rehearsal tooling is needed.

**Beat 6 is honest only with the caption.** `bench/RESULTS.md` says of itself:
"a regression corpus, not a bypass-resistance scoreboard." The figures are
attempts across pinned classes, not distinct attacks, and the out-of-scope
column matters as much as the blocked column. Never say "unbypassable."

**Fallback.** If the full loop is fiddly, beats 2, 4 and 5 stand alone as a
25-second hero. Do not burn a day chasing beat 3.

### End card: the systems grid

One line per system. Every `<N>` is filled from the derivation commands in the
systems map on the day; this file carries none (rule 5). For example:

```
hooks · plan gate · handoff and memory · /recall over the footgun catalog
<N> specialist agents · <N> commands · <N> skills · <N> review workflows
bench: every pinned shape blocked, every out-of-scope shape allowed
built under itself, daily, since 2026
```

---

## ZERO-TO-AHEAD clip (about 15 s)

An empty repo becomes a governed one in one command. Nearly deterministic, so it
can be a scripted recording that re-records itself when the surface changes.

| Beat | On screen | Narration |
|---|---|---|
| 1 | An eight-file repo, `git status` clean | "A repo with nothing in it yet." |
| 2 | `pip install espalier-harness` | "Install." |
| 3 | `espalier init .` and its summary line | "One command." |
| 4 | `tree .claude/` and the hook list | "Hooks, commands, skills, agents, review workflows, the footgun catalog, the memory files." |
| 5 | `claude`, the banner header | "Your first session starts where ours is after months." |

The 2026-09-28 show-readiness walk recorded the install at about 2 seconds and
`init` at 418 ms; there is no receipt in the tree for either. Re-measure on the
day and quote the day's figures or none.

**Don't claim.** A tree view of a hundred-odd files reads as bloat to an expert.
The caption must say the spine is trimmable: `plan_exempt_prefixes` in
`espalier.toml`, `ESPALIER_STOP_GATE`, and maintenance mode are the knobs. The
walkthrough shows them; the clip names them.

---

## WALKTHROUGH: chapters (3 to 4 minutes, narrated, hosted)

Your voice, your machine, the source repo where it says so. Each chapter:
what to do, what is on screen, the honest line, and the claim to avoid. The
chapters absorb what the GIF cannot carry.

1. **Install and init.** The zero-to-ahead clip at speaking pace. Show the
   `espalier.toml` knobs. *Avoid:* implying the seeded docs are finished for the
   adopter; they are a starting point they own.
2. **First session.** The banner, then `/status`: ten lines of harness state.
   *Avoid:* calling the blueprint de-duplicated.
3. **A task through the workflow.** Plan gate, `/implement-task`, the per-step
   trail from `execution_plan.py status`. *Avoid:* implying the harness verifies
   each step's proof. `mark passed` is a self-report; the mechanical backstop is
   the Stop gate's opt-in pytest.
4. **The floor.** Beats 4 and 5, then the why: the accident guard. An agent
   forgets to re-arm hooks it was asked to lower; a settings cleanup empties the
   hooks list (`BC-008-kill-switch-empty-hooks` in the corpus is exactly that
   payload). *Avoid:* claiming agents routinely reach for the kill-switch. The
   maintainer has not seen one do so unprompted.
5. **Recall before a hard edit.** Before a hook edit: `/recall hook authoring`.
   The footgun catalog comes back as up to four candidates; you pick. Say the
   size of what stays out of context until asked. *Avoid:* implying recall is
   always right. It returns lexical neighbours; the caller chooses.
6. **The Stop gate on a real session.** Needs a session with ten or more source
   writes and no review recorded: Claude says done, the gate says review first.
   In default light mode gates 2 and 3 fire only past that floor, gate 1
   (pytest) is opt-in via `ESPALIER_STOP_GATE=full`, and gate 4 (blueprint
   finalize) is silent. So this chapter is filmed at the end of a working
   session, never staged in a short one. *Avoid:* implying it fires on every stop.
7. **Handoff into a second session.** `/handoff`, then a new `claude`: the banner
   carries the decision verbatim. *Avoid:* implying more than one hop from the
   blueprint alone. The durable store is `ESPALIER_MEMORY.md` plus the working
   summary.
8. **A review agent on a real diff.** `/review` or `/adversarial` on a change you
   just made; one real finding. *Avoid:* implying determinism.
9. **A task pack.** The `TP-N.md` shape, `/scope-check`, `/implement-pack`. Keep
   it to the idea: a durable, reviewable, resumable unit of agent work.
10. **The bench.** The differential table; then shape breadth: the Write with
    `safe_dir/../`, the `tee --append`, the `python3` heredoc on stdin, the
    PowerShell `Set-Content`, all resolving to the same deny. Show one corpus
    file open beside its test. *Avoid:* "security boundary." The file says
    "regression corpus."
11. **Built under itself.** This repo's own banner: the depth counter, the
    `Merged:` line, the handoff block. "This is what I see every morning."
    *Avoid:* real paths and usernames in frame; scrub or crop.

**Director's cut, verify first.** When an agent breaks the guard while editing
it in maintenance mode, the guard fails closed on itself and only a human at a
terminal can repair it. Two shapes were seen in September 2026: a broken Bash
extractor left Read and Edit working while every shell call was refused; a
fault above the maintenance gate refused Edit, Write and Bash too, and the
operator repaired the file with a paste-ready one-liner behind the `!` prompt
prefix. The second shape was closed the same day (that call now degrades to an
allow), so it may no longer reproduce. Film it only if it does; it is a trust
signal with narration and a fragility signal without.

---

## README systems map: the spec (the README edit is its own lane)

The README lane owns two edits, not one: this map, and the `## 30-second demo`
prose above it, which still shows the staged kill-switch prompt this plan retired
(rule 4). The GIF must not be embedded above that block; `RECORDING.md`'s
after-recording step says the same.

Directly under the hero GIF. Seven rows, what fires when, one line each, the
knob that softens it where one exists. Counts, if any appear, come from the
derivation commands below, never from a hand-typed number.

| Layer | Fires | Does | Knob |
|---|---|---|---|
| Orient | SessionStart, PostCompact, SubagentStart | Banner, memory digest, blueprint chain, open-PR readout; a cold subagent's orientation | none |
| Route | UserPromptSubmit | Classifies the prompt, injects the routing advisory | none |
| Guard | PreToolUse, ConfigChange | Protected-zone floor, dangerous-command catch, secret-path reads, plan gate | `plan_exempt_prefixes`, maintenance mode |
| Check | PostToolUse, PostToolUseFailure | Written-file validation, reflect trigger every tenth source write, re-derivation on a failed edit | none |
| Gate | Stop, SubagentStop | Four-gate stop sequence; subagent reasoning appended | `ESPALIER_STOP_GATE` |
| Work | commands, skills, agents, workflows | The daily loop, the review roster, the task-pack loop, three review workflows | edit or delete any body |
| Remember | `/recall`, `/handoff`, `memory/`, the cognitive docs | Pull-only footgun catalog, cross-session blueprints, committed memory | none |

Derivation commands for any count that appears on the map or an end card, run
from the source repo root on the day:

```bash
ls tools/cc/hooks/*.py | grep -v '/_' | wc -l          # hooks deployed
ls .claude/commands/*.md | wc -l                        # commands
ls -d .claude/skills/*/ | wc -l                         # skills
ls .claude/agents/*.md | wc -l                          # agents
ls .claude/workflows/*.js | wc -l                       # review workflows
ls espalier/scanners/*.py | grep -v __init__ | wc -l    # scanners
ls bench/corpus/BC-*.json | wc -l                       # bench classes
grep -c '^## ' docs/SHARP_EDGES.md docs/FAILURE_MODES.md docs/STANDING_PRINCIPLES.md
sed -n '18,23p' bench/RESULTS.md                        # the differential table
```

---

## Recording checklist (per take)

- [ ] `echo $ESPALIER_MAINTENANCE_MODE` is blank (beats 1 to 4)
- [ ] recording against the demo-target, not the source repo, and it has never had a session
- [ ] each deny on screen matches a re-drive from today, not this file
- [ ] the agent's reply after each deny is in frame
- [ ] the caption is the honest line; nothing says "unbypassable" or "security boundary"
- [ ] numbers on the end card came from the derivation commands today
- [ ] trimmed to the beat budget; GIF under 5 MB
- [ ] embed verified on github.com, not a local preview

**Ship order:** hero, then launch, then the clip and the walkthrough as
fast-follow. `RECORDING.md` has the tools, the sizing and the embed target.
