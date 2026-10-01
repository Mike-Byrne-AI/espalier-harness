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
   branch. The plan-gate beat edits `src/utils.py`, so seed it. `init` writes
   about a hundred tracked files, so commit again after it or the banner will
   read `N uncommitted changes` instead of `clean`.
   ```bash
   rm -rf /tmp/demo-target
   mkdir -p /tmp/demo-target/src && cd /tmp/demo-target
   git init -q && git branch -M main
   printf 'def add(a, b):\n    return a + b\n' > src/utils.py
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
   With it set, the plan gate is skipped and the protected-zone deny does not
   fire. The `env -u` in the storyboard's re-drive commands scrubs that one
   command only; it does not scrub the shell you launch `claude` from.

4. **Confirm the hooks load.** Open Claude Code in `/tmp/demo-target` and check
   the banner header appears. The header, in the order it prints:
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
   The continuity payload between `Blueprint:` and `Surface:` scrolls, and a
   `Commands:` footer follows. If no banner appears, see the troubleshooting
   table. Quit this session when done.

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

7. **Pre-take check for beat 5: none needed.** The guard's one-line advisory
   (`[write_guard] MAINTENANCE_MODE -- protected-zone check bypassed`) goes to
   stderr, and an allowed hook's stderr reaches only Claude Code's debug log,
   never the transcript (upstream, pinned 2026-09-28). Beat 5's proof is the
   landed edit alone, and the storyboard's caption already stands on that; the
   audit row the bypass writes is the record, counted by `/status --log`.

8. **Recreate the target.** Steps 4 and 6 each opened a session in it, so
   the practice tree has a blueprint chain and a plan. Run the step 2 block
   again. The take runs on a tree that has never had a session, and the hero
   session must be the last one opened there, because `--continue` resumes
   the most recent conversation in the directory.

---

## The two-phase take

The hero is one continuous Claude Code session with a single cut.

**Phase 1, beats 1 to 4, maintenance mode unset.** Open `claude`, let the banner
scroll, type the two prompts from the storyboard, and let each deny land. Keep
the agent's reply in frame after each deny: the reply is the payoff. After beat
4, when the agent has asked you to relaunch, quit the session.

**Phase 2, beat 5, maintenance mode set for this launch only.** In the same
shell:

```bash
ESPALIER_MAINTENANCE_MODE=1 claude --continue
```

`--continue` resumes the same session, so the transcript picks up where beat 4
stopped. Ask the agent to go ahead with the edit it was refused. It lands (the
guard's advisory goes to the debug log, not the screen). Then quit. The
variable was set for that one command and is gone with it.

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
   walkthrough with the hero's two prompts and denies, then add the image as
   the first line under the heading. Keep the alt text on one source line:

   ```markdown
   ## 30-second demo

   ![A Claude Code session under Espalier: a source edit waits until a plan is opened; then an edit to a hook file is refused and the agent asks the operator to relaunch in maintenance mode before it can continue.](bench/demo/espalier-demo.gif)
   ```

   The alt text is mandatory. It is what screen readers read and what shows if
   the image fails to load; keep it a description of what happens, not a slogan.

2. Verify the embed on github.com, then commit: `docs: add demo GIF`.

3. Commit the `.cast` beside the GIF if you recorded with asciinema.

---

## Re-recording cadence

Re-record when:

- A quoted deny changes. `tests/test_demo_end_to_end.py` pins the beat 3,
  beat 4 and Bash-reference blocks clause by clause and the beat 5 advisory
  line verbatim, and checks the beat 2 banner labels against the hook's
  source; `tests/test_bench_demo_script_quotes.py` pins the zone list and the
  relaunch spelling in every demo doc. A red in either is the signal.
- A banner field is added, removed or reordered. The label pin catches a
  renamed or removed label, not a reorder; re-drive the header by eye.
- A major version bump, where the recording's apparent age would mislead.

Do not re-record for cosmetic changes. The behaviour on screen is the value;
polish does not add to it.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Banner says `Status: N uncommitted changes`, not `clean` | `espalier init` wrote tracked files after the seed commit | Commit again after `init`; the step 2 block does. |
| No deny fires; the edit just lands | Maintenance mode is set in the launching shell, or hooks are not wired | `unset ESPALIER_MAINTENANCE_MODE` in that shell, then relaunch. Then `espalier doctor .` and check the wired events: `python3 -c "import json; print(sorted(json.load(open('.claude/settings.json')).get('hooks', {})))"` should list ten events (`ConfigChange`, `PostCompact`, `PostToolUse`, `PostToolUseFailure`, `PreToolUse`, `SessionStart`, `Stop`, `SubagentStart`, `SubagentStop`, `UserPromptSubmit`). Fewer means the settings predate some reporter hooks: `espalier merge-settings .` adds the missing events non-destructively. Re-running `init` does not rewire an existing settings file. |
| Beat 4: the agent edited `CLAUDE.md`, `ESPALIER_MEMORY.md` or a doc and nothing was denied | The prompt did not name the hook file; those files are not in the protected zone | Use the storyboard's prompt verbatim, which names `tools/cc/hooks/session_start.py`. |
| Beat 4: the deny is the one-line Bash form, whose headline is `Bash write to protected harness zone blocked: <path>.` | The agent reached for `sed` or a redirect instead of the Edit tool | Take two, and if it repeats, add "using the Edit tool" to the prompt. The Bash form is real product output but not the block the storyboard films. |
| `init` printed WARN lines or `settings.json (exists — merge manually)` | The target is a reused one | Run the step 2 block again from `rm -rf /tmp/demo-target`. |
| Plan-gate deny says `(complete)` or `(cancelled)`, not `(missing)` | A plan from an earlier take or the practice run is still in the target | Recreate the target (step 8). |
| Deny fires but the words differ from the storyboard | The hook text moved; the storyboard is stale | The hook is the source of truth. Re-drive with the commands under each block in the storyboard and paste the live text there. Never edit the hook to match the doc. |
| The agent's reply after a deny is mushy or retries | Nondeterminism | Take two. The `Do:` clause steers it and it usually follows; nobody has measured the rate, so budget a second take. |
| Beat 5's edit lands but no advisory line appears | An allowed hook's stderr reaches only the debug log, never the transcript (upstream, pinned 2026-09-28) | Expected, always. The landed edit is the proof. |
| Beat 5's edit is still refused after the relaunch | The variable was exported mid-session, or the relaunch dropped `--continue` | Quit fully, then `ESPALIER_MAINTENANCE_MODE=1 claude --continue` as one command. The hooks read the environment at launch. |
| No banner at all | Claude Code was not started from the target directory | Quit and relaunch from `/tmp/demo-target`. Inside the session, `echo $CLAUDE_PROJECT_DIR` should print that path. |
| Banner fields differ from the storyboard | Banner format changed | Update the storyboard's beat 2 block. The exact field set is not load-bearing; the viewer needs to see hook output, not a specific list. |
| Over the beat budget | Title held too long, waiting for "thinking", end card lingering | Title 4 s, end card under 8 s, type at conversational speed. Cut beat 3 before cutting the agent's replies. |
| Too fast to follow | Denies scroll off before they can be read | Hold two or three seconds after each deny before the next prompt. Record at the right pace rather than slowing playback. |
| GIF over 5 MB | Frame rate or window too large | `gifsicle -O3 --colors 64` then `mv` over the embedded name, then `-f 10`, then a smaller window, then render from the `.cast`. |
| Real paths or usernames in frame | Prompt or tab title | `PS1='$ '`, hide the tab title, stay in `/tmp/demo-target` for the whole take. |
| Renders locally, broken on GitHub | GitHub rewrites Markdown and resizes images | Always check `github.com/<repo>/blob/<branch>/README.md` before merging. |

**When in doubt.** The recording's purpose is to show a real session held on
the rails by real hooks. If anything in it could lead a careful viewer to think
it was staged, it fails its purpose: re-record rather than ship a take you
would have to defend. If a hook stops doing what the storyboard says, that is a
regression in espalier, not in the demo. Stop and fix it first.
