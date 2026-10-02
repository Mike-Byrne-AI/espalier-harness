# Demo recording: the how

What to record, beat by beat, lives in [`STORYBOARD.md`](STORYBOARD.md). This
file is everything around the take: the throwaway target, the two-phase
session, the tools, the size budget, the README embed, and the troubleshooting
table at the end. Claude Code cannot record a terminal; this part is yours.

The recording produces `espalier-demo.gif` (or a `.cast` plus the rendered GIF)
in this directory.

---

## Setup checklist

Make a clean environment so the take is reproducible and shows the canonical
messages.

1. **Fresh install, from PyPI, in its own venv.** The demo shows the adopter's
   path, not a source checkout.
   ```bash
   python3 -m venv ~/.venvs/espalier-demo
   source ~/.venvs/espalier-demo/bin/activate
   pip install espalier-harness
   espalier --version
   ```
   `pip install espalier` without the suffix installs an unrelated package
   whose console script is also named `espalier`. Use the full name.

2. **A throwaway demo-target with one source file.** The block starts by
   removing any earlier target, because a reused one carries the last take's
   plan and blueprint and `espalier init` then takes its existing-settings
   branch. The walkthrough's plan-gate chapter asks for the docstring typo to be
   fixed, so the seed carries one. `init` writes about a hundred tracked files,
   so commit again after it or `/status` will read `(N changed)` on its BRANCH
   line instead of a clean branch.
   ```bash
   rm -rf /tmp/demo-target
   mkdir -p /tmp/demo-target/src && cd /tmp/demo-target
   git init -q && git branch -M main
   printf 'def add(a, b):\n    """Retrun the sum of a and b."""\n    return a + b\n' > src/utils.py
   printf '# demo-target\n' > README.md
   git add -A && git commit -qm "seed"
   espalier init .
   git add -A && git commit -qm "espalier init"
   espalier doctor .      # expect: pass or warn (warn is the normal post-init state)
   ```

3. **Maintenance mode is UNSET in the shell you launch from.** Run the unset
   as a command, not a check:
   ```bash
   unset ESPALIER_MAINTENANCE_MODE && echo "[$ESPALIER_MAINTENANCE_MODE]"   # expect []
   ```
   With it set, the plan gate is skipped, the protected-zone deny does not fire,
   and beat 3's `--explain` read-out inverts to `=> MAINTENANCE MODE active` --
   the floor beat filming the floor off. The `env -u` in the storyboard's
   re-drive commands scrubs that one command only; it does not scrub the shell
   you launch `claude` from.

3b. **Pick the permission mode explicitly, on BOTH launches.** A box whose
   default is `dontAsk` refuses the Edit before any hook sees it, so beat 5
   never lands and the deny you are filming is the permission layer, not the
   guard. Use the same mode in phase 1 and phase 2:
   ```bash
   claude --permission-mode acceptEdits
   ESPALIER_MAINTENANCE_MODE=1 claude --continue --permission-mode acceptEdits
   ```
   Under maintenance mode `write_guard` ALLOWS the call, and an allowed hook
   decision falls through to Claude Code's normal permission flow
   (`docs/external/cc-hook-protocol.md`) -- which is exactly where a `dontAsk`
   default stops it. Record which mode you used: the storyboard's measured deny
   rate was taken headless, where there is no permission flow at all.

4. **Confirm the hooks load — from the shell, not by eye.** Do NOT look for
   the SessionStart banner: it is never drawn on screen (an exit-0 hook's plain
   stdout reaches only Claude Code's debug log and the model's context). Earlier
   versions of this step told you to confirm the header appeared, which is not
   a thing that can happen. Check the wiring mechanically instead:
   ```bash
   cd /tmp/demo-target
   python3 -c "import json; print(sorted(json.load(open('.claude/settings.json')).get('hooks', {})))"
   env -u ESPALIER_MAINTENANCE_MODE python3 tools/cc/session_resume.py --explain tools/cc/hooks/session_start.py
   ```
   The first prints every event in `espalier/harness_config.py::HOOK_EVENTS`
   (ten at the time of writing; the troubleshooting table names them). The
   second must carry a line beginning `=> writes DENIED`. If
   either disagrees, see the troubleshooting table. No session is opened, so the
   target stays pristine.

5. **Terminal appearance.**
   - A high-contrast theme. Solarized-dark, Dracula, and the default macOS
     Terminal "Pro" profile all read well.
   - Monospace at 16pt or larger. `Cmd+Plus` to bump, then resize the window
     until the prompt fits.
   - About 1280 by 720. Sixteen by nine.
   - Nothing that names a real path or user: swap to `PS1='$ '` or a dedicated
     recording profile, and hide the tab title.

6. **Practice once without recording.** The first attempt always reveals a
   timing or window-size issue.

7. **Pre-take check for beats 2 and 3: confirm the read-outs actually render.**
   Both are commands the AGENT runs (`/status`'s body is two bash blocks, and
   you ask it for the two `--explain` calls), so what lands in frame is a Bash
   tool-result block, not shell output you typed. Claude Code may render such a
   block collapsed or truncated with a `+N lines` affordance, in which case the
   read-out is no more filmable than the banner was -- the same assumption, one
   layer down, and it is why this step exists. Thirty seconds, in the target:
   open `claude`, type `/status`, and look at whether all ten lines are on
   screen. If they are collapsed, run both beats as PLAIN TERMINAL COMMANDS
   before launching `claude`:
   ```bash
   env -u ESPALIER_MAINTENANCE_MODE python3 tools/cc/session_resume.py --mode status
   env -u ESPALIER_MAINTENANCE_MODE python3 tools/cc/session_resume.py --explain src/utils.py
   env -u ESPALIER_MAINTENANCE_MODE python3 tools/cc/session_resume.py --explain tools/cc/hooks/session_start.py
   ```
   That renders deterministically, costs the "typed inside the session" framing,
   and changes one quoted value: a shell drive before any session reads
   `blueprint=missing`, not `found`. Record which way you went, and re-drive the
   storyboard's `/status` block to match.

8. **Pre-take check for beat 5: none needed.** The guard's one-line advisory
   (`[write_guard] MAINTENANCE_MODE -- protected-zone check bypassed`) goes to
   stderr, and an allowed hook's stderr reaches only Claude Code's debug log,
   never the transcript (upstream, pinned 2026-09-28). Beat 5's proof is the
   landed edit alone, and the storyboard's caption already stands on that; the
   audit row the bypass writes is the record, counted by `/status --log`.

9. **Recreate the target.** Steps 4, 6 and 7 each may have opened a session in it, so
   the practice tree has a blueprint chain and a plan. Run the step 2 block
   again. The take runs on a tree that has never had a session, and the hero
   session must be the last one opened there, because `--continue` resumes
   the most recent conversation in the directory.

---

## The two-phase take

The hero is one continuous Claude Code session with a single cut.

**Phase 1, beats 1 to 4, maintenance mode unset.** Open `claude`, type
`/status`, run the two `--explain` calls, then type the storyboard's single
lockout prompt. Keep the agent's reply in frame: the reply is the payoff,
whether it is reporting a deny or asking your permission before it writes.
When it hands the decision back to you, quit the session.

**A take where no deny fires is still a take.** Measured 2026-10-02 in
headless `claude -p` on Sonnet 5 at default thinking, the lockout prompt drew the
deny in three of five trials; in the other two the agent scoped the change and
asked permission first. Both are on-message and the storyboard carries a caption
for each. Treat three-in-five as an upper bound, not a forecast: your take is
interactive, on your own model and permission mode, and the only interactive data
point on record (Opus 5, 2026-10-01, on the older under-specified prompt) drew
zero. Budget four takes.

**One take is phase 1 AND phase 2, then a rebuild.** Do not shoot three phase-1
takes and pick one afterwards: `--continue` resumes the most recent conversation
in the directory (setup step 8), and rebuilding the target destroys it, so a
phase-1 take you shot two rebuilds ago cannot be continued into. Shoot phase 1,
shoot phase 2, rebuild, repeat -- and keep the best COMPLETE pair.

**Phase 2, beat 5, maintenance mode set for this launch only.** In the same
shell:

```bash
ESPALIER_MAINTENANCE_MODE=1 claude --continue --permission-mode acceptEdits
```

`--continue` resumes the same session, so the transcript picks up where beat 4
stopped. Ask the agent to go ahead with the edit, and it lands (the guard's
advisory goes to the debug log, not the screen). Then quit. The variable was set
for that one command and is gone with it.

**If beat 4 missed, phase 1 is not finished.** Beat 5's caption and the
storyboard's line "the edit refused thirty seconds earlier now goes through" both
need an edit that was actually refused. On a miss take the agent asked permission
instead, so before quitting phase 1, re-prompt the edit plainly and let the guard
refuse it -- then phase 2 means what it says. Without that, what ships reads as
"maintenance mode is how you grant the agent permission," which is the one thing
the mode is not.

Beats 6 and 7 are held frames added in post: the differential table from
`bench/RESULTS.md` and the end card. Re-derive any number on the end card with
the commands in the storyboard's systems-map section on the day.

---

## Recording tools

Each is a one-line install.

### asciinema plus agg (recommended)

Text-native recording. Tiny file, crisp on every viewer, and the `.cast` is a
diffable artifact worth committing beside the GIF.

```bash
brew install asciinema agg
asciinema rec espalier-demo.cast      # Ctrl-D to stop
agg espalier-demo.cast espalier-demo.gif
```

### vhs (for the zero-to-ahead clip)

A tape file scripts the keystrokes, so the clip re-records itself with one
command when the surface changes. Fixed sleeps make it fragile around a live
Claude reply, so it suits the deterministic clip and not the hero.

```bash
brew install vhs
vhs zero-to-ahead.tape
```

### Native screen recording (last resort)

macOS: `Cmd+Shift+5`, record the selected portion, save as `.mov`, then:

```bash
brew install ffmpeg
ffmpeg -i espalier-demo.mov -vf "fps=15,scale=1280:-1:flags=lanczos" -loop 0 espalier-demo.gif
```

Linux: peek or kazam. Windows: ScreenToGif.

---

## Post-processing

1. **Trim** to the storyboard's beat budget. Hold each deny for two or three
   seconds so it lands; hold the end card six to eight seconds; cut everything
   else tight.

2. **GIF under 5 MB.** GitHub renders inline below that and shows a "too large"
   link above it. The optimised file must end up under the name the README
   embeds:
   ```bash
   brew install gifsicle
   gifsicle -O3 --colors 64 espalier-demo.gif -o espalier-demo-min.gif && mv espalier-demo-min.gif espalier-demo.gif
   ```
   Still over: lower the frame rate (`-f 10` is acceptable), shrink the
   recording window, or render from the `.cast` at a smaller size.

3. **Verify the embed on github.com**, on a branch, before merging. Local
   Markdown preview is not the oracle: GitHub strips some tags and resizes
   images to the container.

---

## After recording

1. **Rewrite the README's demo prose in the same lane as the embed.** The
   `## 30-second demo` section still shows the staged kill-switch prompt the
   storyboard retired (rule 4). The GIF must not sit above it: replace that
   walkthrough with the hero's floor read-out and its one lockout prompt, then
   add the image as the first line under the heading. Keep the alt text on one
   source line:

   ```markdown
   ## 30-second demo

   ![A Claude Code session under Espalier: the harness is asked what it will refuse and names one path allowed and a hook file denied; the agent then tries to edit that hook file, is refused, and asks the operator to relaunch in maintenance mode before it can continue.](bench/demo/espalier-demo.gif)
   ```

   The alt text is mandatory. It is what screen readers read and what shows if
   the image fails to load; keep it a description of what happens, not a slogan.

2. Verify the embed on github.com, then commit: `docs: add demo GIF`.

3. Commit the `.cast` beside the GIF if you recorded with asciinema.

---

## Re-recording cadence

Re-record when:

- A quoted deny changes. `tests/test_demo_end_to_end.py` pins the plan-gate,
  protected-zone and Bash-reference blocks clause by clause, the advisory line
  verbatim, the `--explain` read-out against both live drives, and the
  `/status` labels against the live script; `tests/test_bench_demo_script_quotes.py`
  pins the zone list and the relaunch spelling in every demo doc. A red in any
  of them is the signal. The pins key on the OUTPUT's heading, never a beat
  number, so re-cutting the hero does not strand them.
- A `/status` field is added, removed or renamed. The label pin is set-equal
  against a live drive, so it catches all three; it does not catch a reorder,
  so re-drive the read-out by eye.
- The recording model or the default permission mode changes. The beat-4 deny
  rate was measured on one model in one mode, and nothing re-measures it
  automatically; it is the only load-bearing number here with no pin.
- A major version bump, where the recording's apparent age would mislead.

Do not re-record for cosmetic changes. The behaviour on screen is the value;
polish does not add to it.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `/status` BRANCH line reads `(N changed)`, not a clean branch | `espalier init` wrote tracked files after the seed commit | Commit again after `init`; the step 2 block does. |
| No deny fires; the edit just lands | Maintenance mode is set in the launching shell, or hooks are not wired | `unset ESPALIER_MAINTENANCE_MODE` in that shell, then relaunch. Then `espalier doctor .` and check the wired events: `python3 -c "import json; print(sorted(json.load(open('.claude/settings.json')).get('hooks', {})))"` should list ten events (`ConfigChange`, `PostCompact`, `PostToolUse`, `PostToolUseFailure`, `PreToolUse`, `SessionStart`, `Stop`, `SubagentStart`, `SubagentStop`, `UserPromptSubmit`). Fewer means the settings predate some reporter hooks: `espalier merge-settings .` adds the missing events non-destructively. Re-running `init` does not rewire an existing settings file. |
| Beat 4: the agent edited `CLAUDE.md`, `ESPALIER_MEMORY.md` or a doc and nothing was denied | The prompt did not name the hook file; those files are not in the protected zone | Use the storyboard's prompt verbatim, which names `tools/cc/hooks/session_start.py`. |
| Beat 4: the agent asks what to call the project, or what the team name is, and writes nothing | The prompt named no replacement string, so there is nothing to execute | Use the storyboard's prompt verbatim, which names both the file and the new string. An earlier draft said "to our team name" and drew zero denies in three trials. |
| Beat 4: no deny; the agent scopes the change and asks permission first | Expected in about two takes in five -- it routed through `/implement-task` off the seeded `CLAUDE.md` | Not a failure. Keep it and use the storyboard's second caption, or take another. Do not add "right now" or "do not read any other files" to force the deny: that reads as staged, which is the storyboard's rule 4. |
| Beat 4: the deny is the one-line Bash form, whose headline is `Bash write to protected harness zone blocked: <path>.` | The agent reached for `sed` or a redirect instead of the Edit tool | Take two, and if it repeats, add "using the Edit tool" to the prompt. The Bash form is real product output but not the block the storyboard films. |
| `init` printed WARN lines or `settings.json (exists — merge manually)` | The target is a reused one | Run the step 2 block again from `rm -rf /tmp/demo-target`. |
| Plan-gate deny says `(complete)` or `(cancelled)`, not `(missing)` | A plan from an earlier take or the practice run is still in the target | Recreate the target (step 8). |
| Deny fires but the words differ from the storyboard | The hook text moved; the storyboard is stale | The hook is the source of truth. Re-drive with the commands under each block in the storyboard and paste the live text there. Never edit the hook to match the doc. |
| The agent's reply after a deny is mushy or retries | Nondeterminism | Take two. Measured 2026-10-02: when the deny fires, the agent named the relaunch requirement every time. |
| The agent's reply names `plan_guard` as the thing that blocked a `tools/cc/` path | The agent reasoned from the plan-gate section of `CLAUDE.md` and never reached the zone roster. It is wrong: `tools/cc/` is plan-EXEMPT and `write_guard` is the blocker | Harmless on screen, but never caption or quote the hook name from a reply. It happened in three of three trials that predicted a gate. |
| Beat 5's edit lands but no advisory line appears | An allowed hook's stderr reaches only the debug log, never the transcript (upstream, pinned 2026-09-28) | Expected, always. The landed edit is the proof. |
| Beat 5's edit is still refused after the relaunch | The variable was exported mid-session, or the relaunch dropped `--continue` | Quit fully, then `ESPALIER_MAINTENANCE_MODE=1 claude --continue` as one command. The hooks read the environment at launch. |
| No banner at all | Expected, always. The SessionStart banner is never drawn on screen; an exit-0 hook's plain stdout reaches the debug log and the model, and no documented key reveals it | Nothing to fix. Earlier versions of this table blamed the launch directory, which was wrong. The hero's orientation beat is `/status`, whose output is an ordinary command's stdout. |
| `/status` reads `blueprint=missing` | A shell drive before any session, or the read-out was run outside the hero session | Expected outside a session. Filmed from inside the hero session it reads `blueprint=found`, which is what the storyboard quotes; the SessionStart hook started the blueprint at launch. |
| `/status` reads `SURFACE:  DEGRADED`, or a sixth `MISSING:` line appears | A required path is absent from the target | Do not film it. Run the step 2 block again from the start; `init` writes the three `reports/*.json` a clean target needs. |
| Beat 2 prints `command not found: python` before the read-out | The deployed `/status` command body spells the interpreter bare `python`, by design -- the seeded `CLAUDE.md` tells the agent to try `python3` first and fall back | Retake. The agent follows the fallback on most takes; this box has no bare `python`. |
| `/status` or `--explain` fields differ from the storyboard | The read-out's format changed | Re-drive with the commands under each block in the storyboard and paste the live text there; the label and predicate pins will have gone red already. |
| Over the beat budget | Title held too long, waiting for "thinking", end card lingering | Title 4 s, end card under 8 s, type at conversational speed. Trim the `/status` scroll before cutting the agent's reply. |
| Too fast to follow | Denies scroll off before they can be read | Hold two or three seconds after each deny before the next prompt. Record at the right pace rather than slowing playback. |
| GIF over 5 MB | Frame rate or window too large | `gifsicle -O3 --colors 64` then `mv` over the embedded name, then `-f 10`, then a smaller window, then render from the `.cast`. |
| Real paths or usernames in frame | Prompt or tab title | `PS1='$ '`, hide the tab title, stay in `/tmp/demo-target` for the whole take. |
| Renders locally, broken on GitHub | GitHub rewrites Markdown and resizes images | Always check `github.com/<repo>/blob/<branch>/README.md` before merging. |

**When in doubt.** The recording's purpose is to show a real session held on
the rails by real hooks. If anything in it could lead a careful viewer to think
it was staged, it fails its purpose: re-record rather than ship a take you
would have to defend. If a hook stops doing what the storyboard says, that is a
regression in espalier, not in the demo. Stop and fix it first.
