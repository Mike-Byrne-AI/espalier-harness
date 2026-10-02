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
   launch from.** With it set, the protected-zone deny does not fire AND beat 3's
   read-out inverts: `--explain` reports `=> MAINTENANCE MODE active -- ...
   checks are bypassed this session` instead of the floor, so the floor beat
   would film the floor switched off (driven 2026-10-02). You would record a
   dead demo twice over. Run `unset ESPALIER_MAINTENANCE_MODE`
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
   hook. A long read-out is trimmed in post, never retyped shorter.
4. **No staged kill-switch prompt.** Earlier drafts had the operator type "set
   disableAllHooks: true" as the climax. Months of daily self-host use have not
   produced an agent reaching for that on its own, so the prompt read as staged
   and the block read as blocking the user. The floor's real job is the accident
   case: an agent editing its own tooling, a half-applied hook edit, a settings
   cleanup that empties the hooks list. The hero shows that case with an
   ordinary prompt. The floor's reasoning belongs in README prose, not on camera.
5. **Every numbered claim on an end card is re-derived at record time**, with the
   commands in the systems-map section. This file carries no counts of the
   SURFACE it describes -- agents, commands, skills, hooks, bench classes --
   because those change under it. A dated measurement of agent behaviour, with
   its date, model, mode and population, is a RECORD and stays: it is evidence,
   not a count that can drift. Do not delete the rehearsal tables to satisfy
   this rule; they are what replaced a guess.
6. **The hero is the launch gate.** A crisp hero beats a perfect set. Do not hold
   launch for the clip or the walkthrough.

---

## Verified on-screen text

Each block carries its own driven date. Maintenance mode is scrubbed from the
environment for every drive, and the re-drive command under each block scrubs it
again -- that scrub is load-bearing, not decoration (rule 1). The
`✗ … hook blocked` line is Claude Code's UI envelope; every line beneath it is
the hook's `permissionDecisionReason`.

Everything here is pinned by `tests/test_demo_end_to_end.py`: the two deny blocks
and the Bash reference clause by clause, the advisory line verbatim, the
`/status` labels and `blueprint=` value against a live drive
(`test_storyboard_status_readout_labels_are_live`), and the `--explain` read-out
per arm against both live drives
(`test_storyboard_explain_readout_matches_the_live_predicates`). Every block's
zone list and relaunch spelling are pinned by
`tests/test_bench_demo_script_quotes.py`. A quoted output with no pin behind it
is the defect this section exists to prevent.

**The headings below name the output, not a beat.** A pin keyed to a beat number
breaks every time the hero is re-cut, and the hero has been re-cut twice
(2026-09-28, 2026-10-02); the pinned block and the beat that uses it are now
independent, so a renumber cannot red the suite and a re-cut cannot strand a pin.

### Why there is no banner block

The SessionStart banner is **never drawn on screen.** An exit-0 hook's plain
stdout reaches Claude Code's debug log and the model's context window; the
terminal UI renders none of it, and no documented key reveals it (confirmed
2026-10-01 from Claude Code's own session records and from the maintainer, who
has never seen it). Earlier drafts of this file quoted the header as verified
on-screen text and `RECORDING.md`'s setup told you to confirm it appeared. Both
were wrong, and a reader who trusted them would wait for a frame that never
comes. The hero's orientation beat is `/status`, whose read-out is an ordinary
command's stdout and does render.

### The `/status` read-out

`/status` runs two commands: `session_resume.py --mode status` and
`git log --oneline -5`. About ten lines land in frame. Surface counts are elided
with `<N>` because this file carries none of its own (rule 5); on the day they
are whatever the target has. Driven 2026-10-02 on an adopter target that has had
one session, which is the state the beat is filmed in:

```
REPO:     demo-target
SURFACE:  healthy
BRANCH:   main
STATUS:   fingerprint=saved blueprint=found
AGENTS:   <N>  COMMANDS: <N>
```

**`blueprint=found`, not `missing`, and the difference is the beat.** Beat 2 is
typed INSIDE the hero session, and SessionStart on a `startup` source has already
advanced the chain and auto-started a blueprint. A shell drive before any session
reads `blueprint=missing`; both values are correct for their moment, and the one
quoted here is the one the camera sees (driven both ways 2026-10-02). The pin
compares this value against a live in-session drive, so a paste from the wrong
moment reds.

`SURFACE:` reads `healthy` on a clean post-`init` target. If it reads `DEGRADED`,
or a sixth `MISSING:` line appears, a required path is absent -- see
`RECORDING.md`'s troubleshooting table; do not film it.

Unlike the banner, this is an ordinary command's stdout. Caveat worth one
pre-take check (`RECORDING.md` step 7): typed as `/status` it is the AGENT that
runs it, so what reaches the screen is a Bash tool-result block, and a
collapsed or truncated one would make this beat as unfilmable as the banner it
replaced. Confirm it renders, or run the command in the terminal instead.

Re-drive from the demo-target root:

```bash
env -u ESPALIER_MAINTENANCE_MODE python3 tools/cc/session_resume.py --mode status
```

### The per-path enforcement read-out

`--explain` answers what the path-conditioned hooks *will* do, derived from the
hooks' own predicates rather than a re-implementation, so it cannot drift from
enforcement. Two calls, one allowed path and one protected, are the hero's floor
beat. The `live state` line is the only one that varies with the session; the
predicate and verdict lines are the same on any tree. Driven 2026-10-02:

```
$ python3 tools/cc/session_resume.py --explain src/utils.py
Path: src/utils.py

  plan_guard : REQUIRES an active plan  (plan required -- non-exempt path)
  write_guard: allowed -- unprotected
  live state : maintenance mode off; plan none active

  => writes allowed (unprotected); edits require an active plan; none is active.

$ python3 tools/cc/session_resume.py --explain tools/cc/hooks/session_start.py
Path: tools/cc/hooks/session_start.py

  plan_guard : exempt  (exempt -- harness-universal prefix `tools/cc/`)
  write_guard: DENIED -- protected zone `tools/cc/`
  live state : maintenance mode off; plan none active

  => writes DENIED (zone `tools/cc/`); no plan required.
```

This is the most deterministic beat in the hero -- it depends on the path and
the session, never on what the agent decides to do. It states the floor as a
fact before anything tries to cross it, which is why the lockout beat below can
miss without leaving a hole: the deny dramatises what this read-out already
proved.

Two things it DOES depend on. With `ESPALIER_MAINTENANCE_MODE` set the verdict
inverts to `=> MAINTENANCE MODE active` (rule 1), and the `Path:` and predicate
lines are byte-identical either way -- so a paste from a maintenance-on drive
looks right and is not. And an adopter who sets `plan_exempt_prefixes` in
`espalier.toml` changes the `plan_guard :` line for their own source, so the
allowed arm above is this demo-target's, not every tree's; the protected arm is
the same on any tree that has not moved `tools/cc/`.

Re-drive BOTH arms from the demo-target root (the `env -u` is the point):

```bash
env -u ESPALIER_MAINTENANCE_MODE python3 tools/cc/session_resume.py --explain src/utils.py
env -u ESPALIER_MAINTENANCE_MODE python3 tools/cc/session_resume.py --explain tools/cc/hooks/session_start.py
```

### The plan-gate deny

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

### The protected-zone deny on a hook file

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

### The maintenance-mode advisory

After the relaunch the same Edit lands. That landing is the proof on screen: the
edit refused thirty seconds earlier now goes through. The guard also writes one
advisory line to stderr naming the bypass (driven 2026-09-28 with the variable
set):

```
[write_guard] MAINTENANCE_MODE -- protected-zone check bypassed
```

Claude Code's default view never renders an allowed hook's stderr: upstream
states it goes to the debug log only (pinned 2026-09-28), so beat 5 has one
proof on screen, the landed edit, and the caption already stands on it; the
audit row the bypass writes is the record off screen.

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

The plan gate is deliberately NOT in the hero. It fires reliably (measured
below) but opening a plan changes the state the lockout beat runs in, so a
missed lockout would cost a target rebuild rather than a retry. It is
walkthrough chapter 3 instead.

| Beat | Time | Action | On screen | Narration (caption) |
|---|---|---|---|---|
| 1 Title | 0:00 to 0:04 | Title card | `espalier — a spine for your Claude Code work, with a floor the agent cannot switch off from inside the session` | none |
| 2 Orient | 0:04 to 0:10 | `/status` | The read-out, about ten lines | "Every session can name its own state in one command." |
| 3 The floor | 0:10 to 0:18 | Two `--explain` calls, one allowed path then the protected hook | The per-path read-out: the first allowed, the second DENIED with the zone named | "Ask the harness what it will refuse, before anything tries to." |
| **4 Lockout** | 0:18 to 0:34 | Prompt: **"Edit tools/cc/hooks/session_start.py: change the banner title from Espalier-Harness to Northwind."** | Either the protected-zone deny and the agent asking you to relaunch, or the agent scoping the change and asking permission first. Both are the take | "The agent cannot edit its own guardrails. It needs you to act. That is the whole point." |
| 5 Relaunch | 0:34 to 0:40 | Cut. In the shell: `ESPALIER_MAINTENANCE_MODE=1 claude --continue` | The same edit lands (the guard's advisory goes to the debug log, not the screen) | "When you mean it, one relaunch opens the door." |
| 6 Proof | 0:40 to 0:45 | Held frame | The differential table from `bench/RESULTS.md`: no-governance, settings-deny-only and espalier rows | "Every shape we have found is pinned so it cannot reopen. Plain deny rules catch none of them." |
| 7 End card | 0:45 to 0:50 | End card | A systems grid, counts re-derived at record time | "More than a floor. A spine." |

**Beat 4's prompt names the file AND the replacement string, both on purpose.**
The file, because the seeded `CLAUDE.md` quotes the banner and is not a
protected path, so an unnamed prompt lands on an allowed edit and no deny
fires. The string, because without it the agent has nothing to write: an
earlier draft asked for "our team name" and that prompt drew zero denies in
three trials, stopping every time to ask what the team is called. An
underspecified prompt is answered, not executed.

**Beat 4 keeps the agent's reply in frame.** The reply is the payoff: a deny
that steers, followed by an agent that is steered. Earlier drafts cut it to
save seconds. Do not. The block is not the point; what the agent does next is.

**Beat 4's rate is measured HEADLESS, and both outcomes are a usable take.**
Eighteen trials, 2026-10-02, one fresh `espalier init` target per trial, Sonnet 5
at default thinking, driven through `claude -p` with maintenance mode scrubbed
from every child environment. Seventeen are enumerated here and in chapter 3; the
eighteenth was a staged instrument check -- a prompt telling the agent to edit the
hook immediately and read nothing else -- run once to prove the deny reaches the
transcript at all, and not a row anyone should film (rule 4). The trial logs are
session scratch and are not in the tree: re-measure with the procedure in this
paragraph rather than citing these figures as a receipt.

| Prompt | Protected-zone denies | Deny at tool call | Wall clock |
|---|---|---|---|
| Beat 4 as above (imperative, string named) | 3 of 5 | 4 to 6 | 32 to 44 s |
| Same, phrased as a goal rather than an instruction | 1 of 3 | 3 | 48 s |
| Earlier draft, "to our team name" | 0 of 3 | n/a | 15 to 32 s |

The misses are not failures. In every one the agent routed through
`/implement-task` off the seeded `CLAUDE.md`, scoped the change, named what it
would not touch, and asked permission -- one of them also caught two docs that
quote the banner literal and would go stale. That is the same frame as the
climax, reached through the instruction layer instead of the mechanical one. The
two captions:

- deny on screen: "The agent cannot edit its own guardrails. It needs you to act."
- agent asks first: "It will not touch its own guardrails without asking you first."

**Three in five is an upper bound for the take, not a forecast.** It was measured
headless; the take is interactive, on whatever model and permission mode the
recording session uses, and `-p` has no permission flow at all. The one
interactive data point on record points the other way: 2026-10-01, Opus 5 with
`--permission-mode acceptEdits`, zero denies across both deny beats -- on the
older under-specified prompt, so it does not refute this rate, and it does not
support it either. Budget four takes and do not count on the rate.

Do not chase a higher rate by adding "right now" or "do not read any other files
first" to the prompt. That reaches the guard reliably and reads as staged, which
is rule 4's whole objection. Adding TARGET specificity is fair game and is not
the same move: `Espalier-Harness` appears six times in that hook file (four
`[WARN]` strings, the post-compaction header, the Session Start title), so an
agent that asks which one is asking a reasonable question. If that is the miss
you keep getting, name the line instead of the concept -- and re-measure before
quoting a new rate, because the rate above belongs to the prompt above.

**Never caption an agent reply that names a hook.** In three of three trials
where the agent predicted which gate would stop it, it named `plan_guard` for a
`tools/cc/` path. That is wrong: `tools/cc/` is plan-EXEMPT and `write_guard`'s
zone check is what blocks it. The action it took was right and its reasoning was
not, so quote the refusal and the relaunch ask, never the hook name.

**Beat 6 is honest only with the caption.** `bench/RESULTS.md` says of itself:
"a regression corpus, not a bypass-resistance scoreboard." The figures are
attempts across pinned classes, not distinct attacks, and the out-of-scope
column matters as much as the blocked column. Never say "unbypassable."

**Fallback.** Beats 3, 4 and 5 stand alone as a 25-second hero: the floor
stated, the floor met, the door opened. Beat 3 alone carries the floor if beat
4 misses on every take, because it is deterministic.

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
| 5 | `claude`, then `/status` | "Your first session starts where ours is after months." |

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
2. **First session.** `/status`: about ten lines of harness state, then
   `--explain` on one path of each class. *Avoid:* saying the SessionStart
   banner appears on screen -- it never does (see "Why there is no banner
   block"); and calling the blueprint de-duplicated.
3. **A task through the workflow.** The plan gate, `/implement-task`, the
   per-step trail from `execution_plan.py status`. The prompt that measured
   best is a small, specific, boring one -- "There is a typo in the docstring
   in src/utils.py, fix it" drew the plan-gate deny in 2 of 3 trials at tool
   call 2 to 3, in 36 and 50 seconds, where a sweeping "add a module docstring
   to every Python file" drew 1 in 3 and ran past seven minutes. A small task
   earns less deliberation, so the gate gets reached. Note where it ends: the
   agent opens a plan and asks you to approve it, so this chapter also needs
   one click from you on camera. *Avoid:* implying the harness verifies each
   step's proof. `mark passed` is a self-report; the mechanical backstop is the
   Stop gate's opt-in pytest.
4. **The floor.** Beats 3 to 5, then the why: the accident guard. An agent
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
7. **Handoff into a second session.** `/handoff`, then a new `claude`, then
   `/read-summary`: the decision comes back verbatim. Film the summary, not the
   banner -- the continuity reaches the model through the SessionStart hook,
   which draws nothing on screen. *Avoid:* implying more than one hop from the
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
11. **Built under itself.** This repo's own state: `/status`, then
    `/read-summary` for the handoff block. The blueprint depth counter and the
    `Merged:` line are banner fields, so they reach the model and not the
    screen -- say that, and show `session_resume.py --mode status` instead of
    claiming to read them. *Avoid:* real paths and usernames in frame (scrub or
    crop); and never narrate as if the banner were on screen.

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
- [ ] beat 3's two `--explain` calls are in frame, the second carrying a line that begins `=> writes DENIED`
- [ ] each deny on screen matches a re-drive from today, not this file
- [ ] the agent's reply after each deny is in frame
- [ ] the caption is the honest line; nothing says "unbypassable" or "security boundary"
- [ ] numbers on the end card came from the derivation commands today
- [ ] trimmed to the beat budget; GIF under 5 MB
- [ ] embed verified on github.com, not a local preview

**Ship order:** hero, then launch, then the clip and the walkthrough as
fast-follow. `RECORDING.md` has the tools, the sizing and the embed target.
