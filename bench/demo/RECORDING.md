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

1. **The HERO records against a wheel built from HEAD, not the PyPI release.**
   Decided 2026-09-29; this step said "fresh install, from PyPI" until
   2026-10-02 and that was the divergence, not the decision. The reason is the
   pins: `tests/test_demo_end_to_end.py` holds the storyboard's deny text to
   HEAD clause by clause, and a release cut before a hook's wording changed
   prints the retired text -- `v0.8.0b2`'s plan-gate deny still carried a
   sentence about a compatibility alias that HEAD had dropped. A storyboard made
   to match a lagging release reds the suite; a release cut for one sentence is
   a full gate for nothing. The hero never shows `pip install` on camera, so the
   adopter's path is exercised the same either way.

   Build it from a `git archive` export, so nothing in the venv came from a
   dirty working tree. From the repo root:
   ```bash
   rm -rf /tmp/espalier-head-export && mkdir -p /tmp/espalier-head-export
   git archive HEAD | tar -x -C /tmp/espalier-head-export
   python3 -m venv ~/.venvs/espalier-demo-head
   ~/.venvs/espalier-demo-head/bin/pip install --quiet /tmp/espalier-head-export
   ~/.venvs/espalier-demo-head/bin/espalier --version
   ```
   Reinstall into that same venv name; never rename it, and never rename a
   target. `init` bakes the directory name into `ESPALIER_MEMORY.md` and
   `doctor` then warns that the saved reports differ from fresh inference.

   **Before every take, check the installed build against HEAD -- and read the
   diff, do not just count it.** The venv deploys the hooks the camera films, so
   it is the thing that can silently lag. A cheap first look, inside the venv:
   ```bash
   cd /tmp    # NOT the repo root: it shadows site-packages, so you would diff HEAD against itself
   diff -rq "$(~/.venvs/espalier-demo-head/bin/python -c 'import espalier,os;print(os.path.dirname(espalier.__file__))')/_vendor/cc" ~/Developer/espalier-harness/tools/cc
   ```
   Treat that as a FLOOR, never as an all-clear. It reads a tree that came out of
   `git archive`, which reads the git index: `.gitattributes` `export-ignore`
   silently drops tracked paths from an export, so a package path missing from
   the wheel is also missing from this diff and the comparison would agree with
   itself. (Checked 2026-10-02: no `export-ignore` row touches `espalier/` --
   210 of 210 tracked package files are in the archive. That is why the floor is
   usable at all, and it can change with one `.gitattributes` edit.)

   The answer to "does this build film the same as HEAD" comes from the real
   artifact. Run step 2's block to `init` a throwaway target with this venv, then
   diff the DEPLOYED hooks against the source and drive the five outputs the
   camera actually sees -- the `/status` read-out, both `--explain` arms, and the
   two deny payloads. Measured 2026-10-02 that way: nineteen files differed
   between the venv and HEAD and all five outputs were byte-identical, because
   the drift was internal. So a difference is a prompt to look, not an automatic
   rebuild; what forces one is a difference you can see on screen. Rebuilding
   anyway is cheap and removes the footnote.

   The `--version` string does NOT tell you the commit: the package version only
   moves at a release cut, so a HEAD wheel built after `v0.8.0b2` still reports
   `0.8.0b2`. The diff above is the only answer to "what is installed."

   **The zero-to-ahead CLIP is the exception and films the real PyPI install**
   (its beat 2 is `pip install espalier-harness`), because "one command" is the
   whole claim and a local path on screen would undercut it. Shoot the clip from
   a separate venv on the published release. There, `pip install espalier`
   without the suffix installs an unrelated package whose console script is also
   named `espalier`, so the full name is load-bearing on camera.

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

7. **Beats 2 and 3 are shell commands, not prompts. This was measured, not
   chosen.** Run them in the target before you launch `claude`:
   ```bash
   cd /tmp/demo-target
   env -u ESPALIER_MAINTENANCE_MODE python3 tools/cc/session_resume.py --mode status
   env -u ESPALIER_MAINTENANCE_MODE python3 tools/cc/session_resume.py --explain src/utils.py
   env -u ESPALIER_MAINTENANCE_MODE python3 tools/cc/session_resume.py --explain tools/cc/hooks/session_start.py
   ```
   The `cd` is load-bearing and is the one line steps 2 and 4 have that an
   earlier draft of this block did not: run from anywhere else and beat 2 frames
   a real absolute path on its `REPO:` line, which setup step 5 forbids and the
   troubleshooting table tells you to discard the take over.

   Typed as `/status` it is the AGENT that runs the command, so what lands in
   frame is a Bash tool-result block rather than shell output you typed -- and
   on 2026-10-02 Claude Code collapsed it: three of five lines, with
   `... +2 lines (ctrl+o to expand)` standing in for the rest (Opus 5,
   `--permission-mode acceptEdits`, one trial, a freshly `init`-ed target). That
   is the banner's defect one layer down: a channel that reaches the model is
   not a channel that reaches the screen. Earlier versions of this step told you
   to check and decide; the check has been run and the answer is above.

   Expanding the block on camera does not recover the beat. The agent's own
   prose renders in full, so the five lines you want stay buried in a forty-line
   reply -- and the shell drive is the better frame anyway: the floor is stated
   before the agent exists. The one quoted value this changes is
   `blueprint=`, which reads `missing` before any session rather than `found`;
   the storyboard quotes `missing` and
   `tests/test_demo_end_to_end.py::test_storyboard_status_blueprint_value_is_the_pre_session_one`
   pins it against a no-session drive.

   **The check itself stays, because it is the only thing that has ever caught
   this.** Four times now a channel that reaches the model has been assumed to
   reach the screen, and every instance was found by a person provoking it on
   camera -- never by a test, because no in-tree oracle can read another
   process's terminal. So before each take, for every beat whose on-screen text
   is NOT a shell command's stdout, provoke it once and count the clauses in
   frame. Today that list is one item, closed on the take:

   - **Beat 4's protected-zone deny: drawn whole.** Observed 2026-10-03 on
     Claude Code 2.1.274 (the landed take, `bench/demo/espalier-demo.cast`):
     the deny renders as a `⏺ Update(<path>)` tool line with the reason under
     it as an indented `⎿  Error:` line, every clause in frame, and no
     `✗ … hook blocked` line (`STORYBOARD.md`, "The protected-zone deny on a
     hook file", quotes that shape). The earlier figure was a line count of the
     storyboard's own hand-wrapped quote, not of the payload; the payload is four
     clauses (headline, Don't, Do, your-own-source), and
     `tests/test_demo_end_to_end.py::test_recording_step7_closure_states_the_live_clause_count`
     pins that number against the driven hook. Had it truncated, the hero's
     climax would have needed the storyboard's fallback (beats 3 to 5)
     rethought before shooting; it did not.

   Record the date and the Claude Code version beside whatever you find; a new
   Claude Code major reopens this item (see "Re-recording cadence").

8. **Pre-take check for beat 5: none needed.** The guard's one-line advisory
   (`[write_guard] MAINTENANCE_MODE -- protected-zone check bypassed`) goes to
   stderr, and an allowed hook's stderr reaches only Claude Code's debug log,
   never the transcript and never the model (upstream, pinned 2026-09-28). Beat
   5's proof is the landed edit alone, and the storyboard's caption already
   stands on that; the audit row the bypass writes is the record, counted by
   `/status --log`. The storyboard's channel table ("Why there is no banner
   block") and `docs/HOOKS.md`'s "What the debug log gets" labels state the same
   rule; a change to one is a change to all three.

9. **Recreate the target, and clear its Claude Code state outside the tree.**
   Steps 3b and 6 open sessions in it (steps 4 and 7 are shell drives and do
   not), so the practice tree has a blueprint chain and possibly a plan. Run
   the step 2 block again -- and run it after ANY session you opened to look
   around, not just the practice one. The take runs on a tree that has never
   had a session, and the hero session must be the last one opened there,
   because `--continue` resumes the most recent conversation in the directory.

   Rebuilding the tree does NOT clear Claude Code's auto-memory for it: that
   lives under `~/.claude/projects/<slug>/memory/`, where the slug is the
   target's real path with every `/` turned into `-` (`/tmp` resolves to
   `/private/tmp` on macOS, so the slug there is `-private-tmp-demo-target`;
   on Linux it is `-tmp-demo-target`), and it survives every rebuild of the
   target. A rehearsal's memory was cited on camera on 2026-10-03 -- "a
   previous banner rebrand" -- in a clip whose premise is a fresh adopter. The
   same slug directory holds the transcripts `--continue` resumes from, so
   clear the whole slug together with the tree, not just its memory folder:
   ```bash
   rm -rf ~/.claude/projects/-private-tmp-demo-target   # Linux: ~/.claude/projects/-tmp-demo-target
   ```
   On Windows the slug sits under `%USERPROFILE%\.claude\projects\` and is the
   target's path with its separators replaced; find the folder named for the
   target and delete it from PowerShell. Do not move the target to a fresh path
   instead: the storyboard, the step 2 block and the troubleshooting table all
   name `/tmp/demo-target`.

---

## The two-phase take

A short shell preamble, then one Claude Code session with a single cut. Beat 1
is the title card, added in post with beats 6 and 7.

**Beats 2 and 3 come first, in the shell, maintenance mode unset.** Three typed
commands (step 7), before `claude` is running. Nothing about them is
nondeterministic, so they can be re-shot on their own without touching the
session beats.

**Phase 1, beat 4, maintenance mode unset.** Launch
`claude --permission-mode acceptEdits` and type the storyboard's single lockout
prompt. It is the session's FIRST prompt, so the cold-open advisory fires and
the agent opens with a short state readout before it reaches for the edit --
expected, trimmed in post. Keep the agent's reply in frame: the reply is the
payoff, whether it is reporting a deny or asking your permission before it
writes. When it hands the decision back to you, quit the session.

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
in the directory (setup step 9), and rebuilding the target destroys it, so a
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
Claude reply, so it suits the clip and not the hero -- and only since the clip's
beat 5 moved its read-out to the shell (`STORYBOARD.md`); while that beat typed
`/status` into a session, the "deterministic" clip had a live reply in it too.

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
   else tight. Cut on the `.cast`, not the GIF: cap pauses, scale the stream,
   insert holds on the beats, and DROP the events you do not want drawn -- a
   folded or zero-duration event still paints (scrollback is not a frame), and
   a hold under 20 ms hides nothing, because GIF viewers clamp shorter delays
   to 100 ms. Verify every cut with a single-frame probe before the full
   render: all events up to index K at zero duration, then
   `agg --last-frame-duration 1`, then PIL to a PNG you look at. The landed
   take was cut this way on 2026-10-04 (slash-menu draw events dropped; holds
   on the deny, the exit state and the typed relaunch).

2. **GIF under 5 MB.** GitHub renders inline below that and shows a "too large"
   link above it. Measure the file only after the render has exited: a
   backgrounded `agg` render read four seconds in is a partial file, and
   `gifsicle` compresses a truncated GIF without complaint (2.5 MB and 57 s
   were reported for what was a 3.35 MB, 58.5 s render, 2026-10-04). Keep
   every render product under `~` or in the repo, never `/tmp`: a reboot wiped
   the overnight render, and the raw casts in `~` were what survived. The
   optimised file must end up under the name the README embeds:
   ```bash
   brew install gifsicle
   gifsicle -O3 --colors 64 espalier-demo.gif -o espalier-demo-min.gif && mv espalier-demo-min.gif espalier-demo.gif
   ```
   Still over: lower the frame rate (`-f 10` is acceptable), shrink the
   recording window, or render from the `.cast` at a smaller size.

3. **Verify the embed on github.com**, on a branch, before merging. Local
   Markdown preview is not the oracle: GitHub strips some tags and resizes
   images to the container. The embed URL points at `main`, so a branch
   preview proves placement and size, not content: a re-cut GIF shows after
   the merge (or point the URL at `raw/<branch>/` for the check, and back
   before merging).

---

## After recording

1. **The README's demo prose and the embed landed together (2026-10-04).** The
   `## 30-second demo` section quotes the hero's floor read-out and its one
   lockout prompt, with the image as the first line under the heading. The alt
   text stays on one source line, and the URL is absolute: pyproject names
   `README.md` as the PyPI long description and `MANIFEST.in` ships only
   `bench/demo/*.md`, so a relative path renders on github.com and is a broken
   image on the project page. `test_readme_embeds_the_take_with_the_recording_alt_text`
   reads the alt text from the fence below, so a re-cut that changes the alt
   edits it here first:

   ```markdown
   ## 30-second demo

   ![A Claude Code session under Espalier: the harness is asked what it will refuse and names one path allowed and a hook file denied; the agent then tries to edit that hook file, is refused, and asks the operator to relaunch in maintenance mode before it can continue.](https://github.com/Mike-Byrne-AI/espalier-harness/raw/main/bench/demo/espalier-demo.gif)
   ```

   The alt text is mandatory. It is what screen readers read and what shows if
   the image fails to load; keep it a description of what happens, not a slogan.

2. After a re-cut: verify on github.com (step 3 above says what a branch
   preview can and cannot prove), then commit the GIF and the `.cast` beside it.

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
  automatically.
- **Claude Code's tool-result or hook-block rendering changes.** The 2026-10-02
  collapse measurement and the 2026-10-03 whole-deny observation (both step 7,
  Claude Code 2.1.274) are one observation each. Neither can be pinned -- no
  in-tree oracle reads another process's terminal; the test pins the payload's
  clause count, not how a terminal draws it -- so re-run step 7's render check
  on a new Claude Code major before shooting. These and the deny rate are the
  load-bearing numbers here with no pin.
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
| Plan-gate deny says `(complete)` or `(cancelled)`, not `(missing)` | A plan from an earlier take or the practice run is still in the target | Recreate the target (step 9). |
| Deny fires but the words differ from the storyboard | The hook text moved; the storyboard is stale | The hook is the source of truth. Re-drive with the commands under each block in the storyboard and paste the live text there. Never edit the hook to match the doc. |
| The agent's reply after a deny is mushy or retries | Nondeterminism | Take two. Measured 2026-10-02: when the deny fires, the agent named the relaunch requirement every time. |
| The agent's reply names `plan_guard` as the thing that blocked a `tools/cc/` path | The agent reasoned from the plan-gate section of `CLAUDE.md` and never reached the zone roster. It is wrong: `tools/cc/` is plan-EXEMPT and `write_guard` is the blocker | Harmless on screen, but never caption or quote the hook name from a reply. It happened in three of three trials that predicted a gate. |
| Beat 5's edit lands but no advisory line appears | An allowed hook's stderr reaches only the debug log, never the transcript (upstream, pinned 2026-09-28) | Expected, always. The landed edit is the proof. |
| Beat 5's edit is still refused after the relaunch | The variable was exported mid-session, the relaunch dropped `--continue`, or it dropped `--permission-mode` -- under maintenance mode the guard ALLOWS the call, so a `dontAsk` default refuses it after the hook said yes (setup step 3b) | Quit fully, then `ESPALIER_MAINTENANCE_MODE=1 claude --continue --permission-mode acceptEdits` as one command. The hooks read the environment at launch. |
| No banner at all | Expected, always. The SessionStart banner is never drawn on screen; an exit-0 hook's plain stdout reaches the debug log and the model, and no documented key reveals it | Nothing to fix. Earlier versions of this table blamed the launch directory, which was wrong. The hero's orientation beat is the `/status` read-out driven as a shell command, whose stdout does render. |
| The read-out reads `blueprint=missing` | A shell drive before any session -- which is what beat 2 is | Expected, and it is what the storyboard quotes. `found` means a session has already run in this target: recreate it (step 9), or you are filming a tree the take has been through. |
| The read-out is collapsed behind `... +N lines (ctrl+o to expand)` | The read-out was typed as `/status`, so the AGENT ran it and the output is a Bash tool-result block | Expected, measured 2026-10-02. Run beats 2 and 3 as shell commands (step 7); do not film the expand -- the agent's reply around it buries the read-out anyway. |
| Beat 2 prints `SURFACE:  DEGRADED`, a sixth `MISSING:` line, and a real absolute path on `REPO:` | The command was typed outside the demo-target, so it reported on whatever directory you were in (driven 2026-10-02). A hand-typed beat can do this; an agent-run one could not | `cd /tmp/demo-target` first. Discard the take rather than trimming it: the `REPO:` line puts a real path in frame, which setup step 5 forbids. |
| The read-out reads `SURFACE:  DEGRADED` and `REPO:` already reads `demo-target`, or a sixth `MISSING:` line appears | A required path is absent from the target -- as distinct from the row above, where `REPO:` names some other directory | Do not film it. Run the step 2 block again from the start; `init` writes the three `reports/*.json` a clean target needs. |
| `/status` prints `command not found: python` before the read-out | The deployed `/status` command body spells the interpreter bare `python`, by design -- the seeded `CLAUDE.md` tells the agent to try `python3` first and fall back | Not a hero problem since 2026-10-02: beat 2 is a shell command you type with the interpreter you have. It still applies if you film `/status` as a prompt anywhere, in the walkthrough for instance. |
| `/status` or `--explain` fields differ from the storyboard | The read-out's format changed | Re-drive with the commands under each block in the storyboard and paste the live text there; the label and predicate pins will have gone red already. |
| Over the beat budget | Title held too long, waiting for "thinking", end card lingering | Title 4 s, end card under 8 s, type at conversational speed. The five shell lines do not scroll; the length to watch is the agent's cold-open readout on beat 4, trimmed in post. |
| Too fast to follow | Denies scroll off before they can be read | Hold two or three seconds after each deny before the next prompt. Record at the right pace rather than slowing playback. |
| GIF over 5 MB | Frame rate or window too large | `gifsicle -O3 --colors 64` then `mv` over the embedded name, then `-f 10`, then a smaller window, then render from the `.cast`. |
| Real paths or usernames in frame | Prompt or tab title | `PS1='$ '`, hide the tab title, stay in `/tmp/demo-target` for the whole take. |
| Renders locally, broken on GitHub | GitHub rewrites Markdown and resizes images | Always check `github.com/<repo>/blob/<branch>/README.md` before merging. |

**When in doubt.** The recording's purpose is to show a real session held on
the rails by real hooks. If anything in it could lead a careful viewer to think
it was staged, it fails its purpose: re-record rather than ship a take you
would have to defend. If a hook stops doing what the storyboard says, that is a
regression in espalier, not in the demo. Stop and fix it first.
