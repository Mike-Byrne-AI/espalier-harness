# Espalier-Harness Troubleshooting

Symptom-organized lookup for the most common adopter friction points.
For governance-internal footguns (cross-module trace patterns, layer
boundary violations, hook-protocol channel-XOR), see
`docs/SHARP_EDGES.md` in the source tree if you've cloned it.

---

## "Hooks aren't firing"

Claude Code only invokes hooks declared in `.claude/settings.json`. If
nothing fires, work through this list in order:

1. **Confirm the file exists.** `ls .claude/settings.json` — should print
   a path, not `No such file or directory`. If absent, re-run
   `espalier init .`.
2. **Confirm `disableAllHooks` is not set.** Open the file and look for
   `"disableAllHooks": true`. If present, set to `false` or remove the
   line. (The kill-switch path is intentional but easy to leave on.)
3. **Confirm hook scripts exist.** `ls tools/cc/hooks/*.py` — every
   path under `hooks` in `settings.json` must resolve to a real file.
   If `git clean` or a typo nuked the tree, re-run `espalier init .`.
4. **Confirm the interpreter resolves.** `.claude/settings.json` records
   hook commands in exec form: `"command": "python3"` plus
   `"args": ["${CLAUDE_PROJECT_DIR}/tools/cc/hooks/<name>.py"]`. The
   interpreter name (`python3` or `python`) is detected at init time via
   `cli._detect_python_command` and resolved by `PATH` at runtime. When
   that name stops resolving — the interpreter was uninstalled, or the
   file came from another machine — the symptom is Claude Code's own
   notice on every hook fire, `SessionStart hook error` (or whichever
   event fired) followed by `Executable not found in $PATH: "python3"`,
   while the session continues with every guard failing open; the
   statusline reads `espalier: statusline did not run --
   see docs/TROUBLESHOOTING.md` instead of going blank (see the section
   below). Run `espalier doctor .` — it names the wired interpreter and
   the fix — then `espalier init . --rewire-interpreter`, which swaps
   the interpreter at every hook entry and the statusline and writes a
   backup first. Plain `espalier init .` does not repair this: it never
   overwrites an existing `settings.json`, and renders
   `settings.json.new` beside it instead when the fresh render differs.
5. **Confirm Claude Code is reading the project settings.** The CLI
   loads `.claude/settings.json` from the working directory at launch.
   If you launched `claude` from a parent directory, hooks won't see
   this project. `cd` into the project root first.
6. **Confirm each entry can fire.** A hook can be present, wired and
   still dead: its command runs no interpreter (an `echo`), its entry is
   missing from an event that exists, it sits under the wrong event or
   with a matcher that excludes the tools it must see, or it is still in
   the pre-v0.6.5 shell form. `espalier doctor .` names the entry and
   which half is wrong; `espalier merge-settings . --repair` rewrites
   espalier's own entries to canonical (backup first, every removal
   listed) — plain `merge-settings` adds a missing event and never
   touches an entry inside one.
7. **If you pressed Ctrl+C at init's `Wire them now?` question.** That is
   the first thing init asks when it finds your own `settings.json`, and
   init stops right there: the hook and tool scripts under `tools/cc/`
   are deployed, `.claude/settings.json` is unchanged (hooks NOT wired),
   and the rest of the deploy did not run — init says so and exits 130.
   Re-run `espalier init . --wire-hooks` to finish in one shot, or plain
   `espalier init .` to be asked again. Enter or Ctrl+D at the question
   means No: init continues, preserves your file, and prints the
   `merge-settings` command that wires the hooks later.

---

## "The statusline reads `espalier: statusline did not run`"

That line is printed by the shell, not by espalier's statusline script,
when the script's command failed to run — on macOS and Linux by the
`||` clause in the statusline command, on Windows by the deployed batch
shim `tools/cc/statusline.cmd` that the command runs. The shell cannot
tell why, so the line names no cause. In order of likelihood:

1. **The hook interpreter no longer resolves.** The same session shows
   `SessionStart hook error` and `Executable not found in $PATH: "..."`
   on every hook fire, and every guard is failing open. Follow step 4 of
   "Hooks aren't firing" above: `espalier doctor .`, then
   `espalier init . --rewire-interpreter`.
2. **`tools/cc/statusline.py` is missing** (a clean, a partial deploy).
   `espalier doctor .` lists the managed files that are absent;
   `espalier init .` re-deploys a managed file that is missing or
   drifted.
3. **Something else.** Run the `statusLine.command` from
   `.claude/settings.json` by hand from the repo root, or start
   `claude --debug`, which logs the exit code and stderr of the first
   statusline run.

If the statusline goes **blank** instead, your `settings.json` predates
the fallback (installs rendered before it keep their statusline:
`merge-settings` adds espalier's `statusLine` only when the key is
absent, and `--rewire-interpreter` swaps only the interpreter the line
names), or it was rendered on the other kind of host and carried in by a
tracked `settings.json` — a `||` clause cannot parse under Windows
PowerShell 5.1, and a POSIX shell cannot run the `.cmd` shim. `espalier
doctor .` says which, and a fresh `espalier init .` renders
`settings.json.new` beside your file when the render differs — take its
`statusLine` line. If there is **no statusline at all** on a wired
install, the file was wired before the merge learned to add the key:
`espalier merge-settings .` adds it (a `statusLine` of your own is never
touched; set the key to `null` to keep the statusline off, since a present
key is never rewritten), and `doctor` names this state too.

---

## "write_guard blocked something it shouldn't have"

`write_guard` blocks writes to **protected harness zones** — every path in
the `tools/cc/` and `cc/` trees,
plus `espalier/` and `.github/workflows/` on the self-host repo,
and the exact files `.claude/settings.json`, `.claude/settings.local.json`,
`.github/workflows/harness-guard.yml`, `.espalier/integrity.json`, and
`.espalier/freshness.json`. Only those two settings files are protected inside
the `.claude/…` tree — commands, skills, agents, and workflows there are freely
editable. The block is mechanical — no per-edit override.

### When you intended to edit harness internals

This is "maintenance mode" territory. Exit Claude Code, then relaunch
with the env var set in the parent shell. `--continue` resumes the session
you were denied in; a bare `claude` starts a new conversation and a new
blueprint node:

```text
POSIX / Git Bash / WSL:  ESPALIER_MAINTENANCE_MODE=1 claude --continue
PowerShell:              $env:ESPALIER_MAINTENANCE_MODE="1"; claude --continue
cmd.exe:                 set ESPALIER_MAINTENANCE_MODE=1 && claude --continue
```

The var must be set **before** launching `claude` — mid-session
inline assignment via a Bash tool call does not propagate to
already-running hook subprocesses (the env is read at fork time).

When `ESPALIER_MAINTENANCE_MODE=1`, `write_guard` skips the protected
zone check, `plan_guard` skips the plan-required check, `stop_gate`
skips two hygiene gates, and `subagent_stop` skips its blueprint append
(a subagent's reasoning is not captured while it is on). Dangerous-pattern
checks and the speed-bump checkpoints still run.

### When you want a narrow carve-out for your own source code

If you're editing your own `src/` and the harness's plan-required rule
keeps firing, add the prefix to `espalier.toml`:

```toml
plan_exempt_prefixes = ["src/myapp/"]
```

This is the right knob for adopter customization. Reach for
`ESPALIER_MAINTENANCE_MODE` only when actually editing the harness.

---

## "`espalier doctor` returns warn"

On an initialized repo `doctor` runs six checks — `presence` (managed
surface exists), `audit` (canon agrees with disk), `reflect` (surface
has not drifted), `recover` (recovery state is sane), `diff` (saved
fingerprint matches current state) and `self_host`. A `source_checkout`
runs `presence` alone, and an uninitialized repo reports no checks at
all, so the roster you see depends on the mode printed alongside it.

Only three of the six can produce `warn`: `presence` when the managed
surface is partial, `reflect` when it finds drift, and `diff` when the
saved fingerprint no longer matches. `audit`, `recover` and `self_host`
either pass or fail — they never warn. `warn` means something noticed
drift but the harness is still functional. Common causes:

- **A reporter hook is not wired.** `reporter hook not wired: <script> is
  on disk but has no executable, correctly-matched wiring under the
  '<event>' event` names a hook that injects, records or advises and never
  blocks (`subagent_start`, `context_reinject_failure`, `post_compact`,
  `reflect_trigger`, ...), so nothing failed visibly while its job went
  undone. The line carries the remedy for its shape: a missing event is
  added by `espalier merge-settings .` (unless the merge would refuse the
  file, and then the line says so); an entry missing from an event that
  exists, one whose command runs no interpreter, one under the wrong
  event or with a narrowed matcher, or one still in the pre-v0.6.5 shell
  form, is rewritten by `espalier merge-settings . --repair`, which
  touches only entries naming espalier's own scripts (and lists every one
  it removes), keeps a `.bak` of the file first and re-checks the wiring after the
  write (the plain merge adds nothing inside an existing event and never
  moves an entry or widens a matcher; `upgrade` never rewrites your
  settings.json either, and says so when a gate is dead). The
  blocking gates are a separate, failing check with the same shapes and
  the same remedy; this one only warns.
- **`reflect` found surface drift.** The likeliest cause on an ordinary
  repo, and the one that surprises people: `reflect` link-checks every
  public markdown file in your tree — *yours included, not just ours* —
  so a single broken relative link anywhere reports `primary_reason:
  reflection found surface drift`. Fix the link, or leave it; nothing
  is mis-wired.
- **No fingerprint baseline yet.** A fresh `git clone` with no
  `espalier init` ran shows `source_checkout` status and passes
  cleanly. After `init`, `doctor` saves a baseline; subsequent runs
  diff against it.
- **`diff` is comparing against a stale baseline.** If you've hand-edited
  an agent or command body, the next `init` preserves your file (marker
  discipline) — but the saved fingerprint no longer describes the tree,
  so `diff` warns. Re-run `espalier fingerprint .` and it clears, with
  your edit untouched. Note what this is *not*: `doctor` never compares
  your file against the packaged one, so there is no byte-divergence
  check and a hand-edited body does not warn on its own account.
- **A seeded doc came back into the fingerprint** (`Large files detected`
  over a catalog you did not write, or a new `docs_heavy` profile): its
  first-line `espalier:seed-version` stamp is gone. That stamp is what keeps
  a seed out of your fingerprint, docs surface and grounding floor, and
  `doctor` names the file and prints its stamp. Do *not* re-run
  `espalier fingerprint .` first; that bakes the noise into the baseline. To
  keep your edits, paste the printed stamp back as line 1, above everything
  else. It is the exact line `init` writes for that file today and needs no
  git or committed copy: the stamp records the packaged body's digest, so
  above an edited copy it keeps mismatching and every later `init` and
  `upgrade` preserves the file. Above a copy that still matches today's
  packaged bytes it restores the untouched status, so the next packaged
  change refreshes it again; above a legacy copy of an *older* packaged body
  your copy is kept but stops receiving packaged updates, and delete-then-
  `init` is that copy's path to current bytes.
  Only for a copy you never edited, delete the file and re-run
  `espalier init .`, which re-seeds the *packaged* body -- for
  `docs/CONVENTIONS.md` and `docs/SHARP_EDGES.md` that is the near-empty
  stub, and your grounding would be gone. Then re-fingerprint if you
  already had.

---

## "Stop event keeps blocking me"

`stop_gate` runs at every Stop event (Claude Code finishing a turn).
Four gates fire in sequence:

| Gate | Default | What it checks |
|---|---|---|
| 1 | Off (opt in via `ESPALIER_STOP_GATE=full`) | `pytest -m "not slow"` passes |
| 2 | On | After 10+ writes, the `docs-maintainer` subagent has run and changed docs (`.espalier-state/docs_refreshed`) |
| 3 | On | After 10+ writes, the `code-reviewer` subagent has run (`.espalier-state/code_reviewed`) |
| 4 | On (always silent) | Cognitive blueprint finalized |

Most common block: **gate 3** after a long session, asking Claude to
dispatch the `code-reviewer` subagent (`subagent_type='code-reviewer'`
is the message's spelling, for Claude). Claude normally does that itself
on reading the message; to force it from your side, mention the same
subagent in a prompt -- the documented operator spelling, which dispatches
the identical agent:

```
@agent-code-reviewer review this session's diff for correctness and style;
report findings with file:line and severity
```

When the subagent finishes, the SubagentStop hook writes
`.espalier-state/code_reviewed` (which agent ran and what it concluded)
and later Stop events in the session pass. Asking for a review is not
enough: the gate reads that record, so it re-arms on the first Stop of
every turn until a review has actually run (the continuation's own Stop
passes by the hook protocol's loop guard). If the diff was reviewed some
other way, record that judgement rather than skipping the gate -- write
the file as `{"agent": "operator", "note": "<a sentence saying how>"}`,
saved as UTF-8. On Windows PowerShell 5.1, `>` and `Out-File` write UTF-16
with a byte-order mark, which the gate reads; a file it cannot decode is
refused with the encoding named, never honoured (`Set-Content -Encoding
utf8` is the sure spelling). The gate announces on stderr when it honours
one, and a note under 20 characters is refused. Gate 2 honours the same
record in `.espalier-state/docs_refreshed`.

To skip gates 2 and 3 entirely (e.g., harness self-edits), launch with
`ESPALIER_MAINTENANCE_MODE=1`. Gate 1 (pytest) is opt-in; gate 4
always runs and is silent.

---

## "I want to uninstall everything Espalier wrote"

```bash
espalier clean-generated --execute .
```

This removes every file carrying the `# espalier:managed` marker — your
`.claude/` agents, commands, and skills, and the `tools/cc/` hook
scripts — with the bytecode caches under them, prunes any managed
directory left empty afterward, and strips what `init` wrote into
`.claude/settings.json`: the hook entries, the `statusLine` that ran the
deleted `tools/cc/statusline.py`, and the managed marker. Your own keys in
that file stay.

**It leaves substantially more than it removes, and that is deliberate:
what survives is the material you were invited to edit and own, plus
per-machine runtime state.** Everything without the marker is preserved —

- your hand-edits, and the seed `CLAUDE.md` / `ESPALIER_MEMORY.md`;
- every doc `init` seeded, which is most of `docs/` plus the `memory/`
  and `task-packs/` directories it created — **this troubleshooting file
  is one of them**;
- your `.claude/settings.json`, and any `settings.json.bak` a merge took;
- the runtime state under `.espalier/`, `.espalier-state/`, `reports/`
  and `cc/blueprints/`;
- anything `espalier install-ci` wrote — `tools/cc/ci_guard.py` and
  `.github/workflows/harness-guard.yml`.

The entries `init` appended to your `.gitignore` are retired one by one as
nothing needs them: an entry that still guards a preserved file (the
`settings.json` line while that file exists, `/reports/` while reports
remain) stays, so the runtime state above never becomes stageable, and the
report lists both under `gitignore_entries_kept` and
`gitignore_entries_removed`; for each kept entry, `gitignore_entries_kept_for`
names a surviving path that keeps it — the first one found, not necessarily
the only one — so a line kept for a file of your own (a `.new` of yours that
`.claude/*.new` matches) is explained rather than left for you to hunt down. Deleting that file does not retire the line by itself: re-run
`clean-generated` once nothing matches. Only the lines inside the harness's own block,
between its header and its end marker, are ever rewritten; on a tree
initialised before the end marker existed, the block ends at the first blank
line or the first line that is not one of the harness's entries, and nothing
past that edge is touched.

So `clean-generated --execute` does **not** produce a bare tree. For the
exact list on *your* repo rather than the categories above, read the
`preserved_user_files` and `preserved_local_runtime` arrays in its JSON
report — between them they name every surviving path the harness wrote,
derived from the same inventory the deploy loop uses. The `settings.json.bak`
copies a wire took of your own settings are listed again under
`settings_backups_kept`, in ladder order, so you can see how many remain. A
re-wire over bytes an existing copy already holds adds none from now on;
duplicates an earlier version left are kept, never pruned. Delete those paths
by hand if you want the tree back to pre-Espalier. `espalier doctor .` on
the emptied tree reports it as not on disk rather than as a broken install,
names the runtime state still there (the saved plan and the markers under
`reports/` and `.espalier/`), and prints the reinstall command; once you
delete that state it reports the tree as never initialized. Your
`.claude/settings.json` stays either way, unwired.

Run it **without** `--execute` first (`espalier clean-generated .`) — the
default is a dry run that prints exactly which paths would be removed,
deleting nothing. Add `--execute` once the preview looks right. Your own
`espalier.toml` (if you wrote one) is never touched — it isn't
harness-generated, so cleanup leaves it alone.

If you *also* installed the engine as a package — `pip install -e .` from a
source checkout, or `pip install espalier-harness` once that channel is
published (it is not yet) — that install lives outside the repo and is not
touched here; remove it separately with `pip uninstall espalier-harness`. A
fusion vendors the engine in-tree, so there is no separate package to remove.

---

## "`/debug`, `/review` or `/status` isn't Claude Code's version"

Expected. Espalier ships three commands whose names match Claude Code
built-ins, and **a project-level skill or command wins over a bundled
one of the same name** — that is Claude Code's documented precedence
(enterprise → personal → project → bundled), not something the harness
does. No warning is shown when it happens, which is why this entry
exists.

| You type | You get | Claude Code's version does |
|---|---|---|
| `/debug` | Espalier's error-trace walkthrough (consults the footgun catalog first) | Enables debug logging and reads the session debug log |
| `/review` | Espalier's per-file correctness review of the current diff | Alias for `/code-review` — diff review with `--fix`, `--comment`, `ultra` |
| `/status` | Espalier's 10-line harness state readout | Session and account status |

Espalier's versions are deliberate: each is wired into this harness's
agents, blueprint chain, and footgun catalogs, which the built-ins know
nothing about. Where you want the built-in instead:

- **`/review`** — use **`/code-review`**. Espalier ships no skill by that
  name, so the full built-in (including `--fix`, `--comment`, and the
  `ultra` cloud review) is always reachable. Only the short `/review`
  alias is taken.
- **`/debug`, `/status`** — no unshadowed alias exists. Turn Espalier's
  entry off if you would rather have that name free:

  ```jsonc
  // .claude/settings.local.json
  { "skillOverrides": { "debug": "off" } }
  ```

  `skillOverrides` is Claude Code's documented setting for disabling a
  skill checked into a shared project repo, so you need not edit a
  managed file to do it; `"off"` also drops the entry from the `/` menu.
  Espalier's capability is not lost either way — `/status`'s readout is
  also what `espalier doctor .` prints from the terminal.

To keep both names, rename your copies in `.claude/skills/` and
`.claude/commands/` — they are yours after `init`. Renaming a *managed*
file makes `espalier audit .` report it as divergent, so prefer
`skillOverrides` unless you mean to own the file.

---

## Still stuck?

- For a known-footgun lookup matching your symptom, search the source
  tree's `docs/SHARP_EDGES.md` if you have the harness cloned. It's a
  taxonomy of bypass classes and edge cases, not a how-to.
- For an audit of what the harness deployed vs what should ship,
  `espalier audit .` lists every managed file with its expected hash.
- For repo state introspection, `espalier doctor .` summarizes
  presence + audit + diff in one report.
