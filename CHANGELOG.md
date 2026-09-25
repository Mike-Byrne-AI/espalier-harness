# Changelog

All notable changes to Espalier-Harness are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
While pre-1.0, minor version bumps may include breaking changes.

---

## [Unreleased]

## [0.8.0b1] — 2026-09-24

The first beta of the 0.8 line and the first public release. Since 0.8.0a13 the
harness gained a second install model (`espalier fuse`), a non-destructive
`espalier upgrade`, `espalier merge-settings` and `espalier selfcheck`, one-time
speed-bump confirmations before hard-to-reverse commands, an enforcement audit
log read by `/status --log`, the `/recall` and `/read-summary` commands,
`espalier strengthen`, two more hooks (twelve wired across ten events), and
Python 3.10 through 3.14 in the pull-request matrix, alongside a long run of
guard fixes: read-only commands are no longer denied, several regex hang
classes on the pre-tool-use path are closed, and Windows and Git Bash hosts are
read the way their shells spell paths. Upgrading from 0.8.0a13 takes three
manual steps, each spelled out below: rename `MEMORY.md` to
`ESPALIER_MEMORY.md`, re-run `espalier install-ci` for the repaired workflow and
its head-bound approval marker, and delete the five `Read()` deny rules from
`.claude/settings.json`. This section is the adopter-facing summary of the
development record since 0.8.0a13; the record itself is kept, unedited,
in the maintainers' tree.

### Added

- **`espalier fuse <host> --out <dir>`:** a new install model that builds a "fusion"
  repo (a copy of your project with the harness overlaid at the root), so you can adopt
  the harness without a `pip install`. Both originals are left untouched.
- **`espalier upgrade .`:** a non-destructive way to re-deploy a stale committed harness
  after you bump the engine. Dry run by default; `--execute` re-deploys managed assets,
  merges settings (your keys preserved, a `.bak` written) and refreshes the integrity
  manifest, and never rewrites your hand-authored `ESPALIER_MEMORY.md`, `CLAUDE.md` or
  docs. The dry-run preview also names the legacy `MEMORY.md` rename when it finds one.
- **`--wire-hooks` on `init` and `fuse`:** arms the harness in a single command when you
  already have a `.claude/settings.json` that carries permissions but no Espalier hooks.
  On a TTY, `init` also offers the same key-preserving merge once (default no); off a
  TTY (CI, scripts, captured output) it never prompts. An existing settings file is
  still never auto-edited and a malformed one is still refused.
- **`espalier strengthen` and the `/strengthen` command:** mechanically enumerates a
  repo's untested public Python symbols and risk-ranks the gaps into an advisory report.
  No LLM, no auto-commit, and it never writes a test; it ends with a pointer to
  `/test-this`.
- **`espalier verify-landing <pack>`:** classifies a task pack's claimed files as
  landed, drifted or owed against git.
- **`espalier surface-impact <pack>`:** a pack pre-flight that reports the
  shipped-surface obligations a pack's declared new files imply (count pins, mirror
  parity, hygiene, provenance) before the build.
- **`espalier selfcheck`:** runs the bundled host-agnostic engine-integrity tests
  against the installed engine, and `selfcheck --contracts <repo>` runs the three
  contracts that read your deployed tree.
- **`espalier merge-settings`:** the key-preserving merge of espalier's hook wiring into
  an existing `.claude/settings.json`, on demand (`init --wire-hooks` performs the same
  merge); `--add-allows` appends the profile's allow rules after yours and `--repair`
  rewrites espalier's own dead hook entries, a `.bak` written first.
- **New flags on existing verbs:** `fuse --fresh` and `--no-init`, `strengthen --top-n`
  and `--skip-fan-in`, `surface-impact --accept-surface-gap`, `scan --baseline`, and
  `memory prune --keep-newest`.
- **Two new hooks, `subagent_start.py` (SubagentStart) and `context_reinject_failure.py`
  (PostToolUseFailure),** bringing the wired hook count to 12. They inject orientation
  for a cold subagent and re-derivation guidance after a failed Write or Edit, and never
  block.
- **Speed-bump confirmations:** a one-time "re-issue the same command to proceed" prompt
  before hard-to-reverse or governance-weakening actions, including force-push,
  publishing a release tag, `rm -rf`, permanently deleting untracked files with `git
  clean -f` (silent on the `-n` / `--dry-run` preview), discarding uncommitted tracked
  work with a bare `git checkout <path>`, disabling a governance hook, and external MCP
  side-effect writes (send, delete, trigger).
- **`CP-FETCHEXEC`, a speed bump for download-and-execute on both shells.** A fetch
  handed straight to an interpreter in one statement (`curl … | sh`, `bash <(curl …)`,
  `bash -c "$(curl …)"`, `eval "$(curl …)"`, and on PowerShell `irm … | iex`, the
  `Net.WebClient` `DownloadString` forms, `[scriptblock]::Create((irm …))`) draws one
  deny that clears on re-issue, keyed per invocation. A fetch piped to local code as
  data (`| python3 -m json.tool`, `| perl -pe`, `| node -e`) stays silent, as does a
  search, an echo or a quoted mention of the idiom. Declared limits, documented rather
  than implied: the two-statement download-then-run form and a fetch held in a variable.
- **Everyday enforcement denials in the governance audit log, plus `/status --log
  [N]`.** Every protected-zone block (Write/Edit, Bash, PowerShell, MCP), every
  dangerous-command block and every `plan_guard` no-active-plan block now appends a
  metadata-only JSON record to `~/.espalier/audit/<repo>-<date>.log` (best effort, never
  file contents). `/status --log` tails the current repo's denials, filtered clear of
  advisory records; `docs/HOOKS.md` documents the event vocabulary.
- **`/status --explain <path>`:** a read-only report of what the path-conditioned hooks
  would do on a repo-relative path and why: plan-gated or plan-exempt and by which rule,
  inside a `write_guard` protected zone or an exact protected file or unprotected, the
  live maintenance-mode effect, and a one-line net verdict. Every verdict is read from
  the hooks' own predicates rather than re-implemented, so it cannot drift from what
  they enforce.
- **`/recall`:** returns up to four candidates from two differently calibrated rankers,
  alternating, for you to pick between, drawn from your `memory/`, the shipped
  sharp-edges and failure-mode references and `docs/STANDING_PRINCIPLES.md`; it
  suppresses only out-of-vocabulary queries, not off-topic ones.
- **`/read-summary`:** re-displays the post-compaction "pick up where we left off"
  summary, backed by an always-current working-summary document and a durable
  per-session archive that survives once Claude Code garbage-collects the session
  transcript.
- **`docs/ADOPTING.md`, and a grounding nudge from `espalier doctor`:** after `init`,
  `doctor` now points an un-grounded repo at `/analyze` (the step that populates
  `docs/CONVENTIONS.md` from your own code), and one onboarding document names the whole
  post-install sequence that the `/analyze` references previously framed only as drift
  detection.
- **`docs/MEMORY_SYSTEMS.md` and `examples/auto-memory.template.md`:** a reference for
  the distinct "memory" systems in play (Claude Code's `CLAUDE.md` and auto memory, plus
  the harness's committed `memory/`), the two files both named `MEMORY.md`, and a
  sorting rule for which one owns a given note. The template is a drop-in starter for
  your own auto-memory index.
- **`espalier init` now seeds a curated subset of the portable-knowledge docs:** hooks,
  workflow, task recipes, failure modes, freshness and the environment catalog reach an
  in-place install, not just `fuse`. Each is seeded once and left editable, refreshed on
  re-init only while it still matches the copy it was deployed from (the seed stamp,
  under Fixed); the example-bearing ones carry a deploy-time header noting that the
  examples describe the harness's own conventions and should be adapted to your repo.
- **Two advisory `/scan test_loosening` findings, `nondiscriminating_hook_assert` and
  `nondiscriminating_hook_allow`.** Under the hooks' exit-code protocol a deny is
  signalled by exit 0 plus a decision on stdout, so a deny-intent or allow-intent test
  that invokes a hook and observes only the process return code cannot fail for the
  reason it names. Advisory only, not a release gate.
- **A SessionStart early warning for nested-repo litter:** an untracked leftover `git
  worktree` or clone lingering in the working tree is named on stderr with a
  remediation, and the check stays silent when the tree is clean. Non-blocking,
  fail-open and bounded, so it never crashes or slows session start.
- **More hard-won lessons in the shipped `docs/FAILURE_MODES.md` and
  `docs/SHARP_EDGES.md` references, reachable through `/recall`:** an unattended run
  that is mechanically green but incomplete; a paraphrased command goal that skips the
  steps nobody transcribed; a friction-bypass flag that makes goal-text completeness
  load-bearing; one planning document asserting a change of state about another that is
  never told; a guard introduced later than the thing it guards refusing its own
  history; unmeasured command latency; efficacy claimed but not measured; timing-based
  concurrency tests that false-green; and several git, freshness and Windows-shell
  footguns.
- **Published artifacts now carry a verifiable build-provenance attestation.** The
  publish workflow emits a signed SLSA provenance for every artifact it builds, before
  the upload step, so a broken attestation fails the job rather than shipping an
  unverifiable wheel. A consumer checks it with `gh attestation verify <artifact> --repo
  <slug>`. The emitting half has not yet been exercised against a real download, so the
  consumer-facing half is still unproven.

### Changed

- **Breaking:** the committed project-memory file is now `ESPALIER_MEMORY.md` (it was
  `MEMORY.md`). Claude Code's machine-local auto memory uses a hardcoded `MEMORY.md`, so
  every repo carried two files with that name. `espalier init` deploys the new name and
  every hook (SessionStart digest, memory autoprune, reflect, session resume) reads it.
  Migration: run `git mv MEMORY.md ESPALIER_MEMORY.md`. If `init` finds a legacy file
  and no new one it prints that nudge rather than deploying a fresh file over your
  existing memory, and `upgrade`'s dry-run preview now surfaces it too.
- **Breaking:** `espalier init` no longer writes `Read()` deny rules into
  `.claude/settings.json`. Configuring any `Read()` deny makes Claude Code prove which
  files a Bash command reads before running it, and a command it cannot resolve
  statically raises an interactive permission prompt that outranks `bypassPermissions`,
  so the five rules every profile used to emit (`Read(./.env)`, `Read(./.env.*)`,
  `Read(./secrets/**)`, `Read(./**/.aws/credentials)`, `Read(./**/credentials.json)`)
  disabled bypass mode. The same paths are now denied at the hook layer by
  `write_guard`, for the `Read` tool as well as Bash and PowerShell. Migration: delete
  those five `Read()` deny entries from an existing `settings.json` by hand.
- **Python 3.10 through 3.14 are supported and CI-tested.** The declared support range
  and the CI matrix had diverged; the full interpreter matrix runs on pull requests.
- **CLI ergonomics:** the repo-path argument is optional and defaults to `.` (so
  `espalier diff` works like `espalier diff .`), `espalier --help` shows a clean
  `espalier <command> ...` usage line, a denied dangerous command prints a plain-English
  description and a way forward instead of a raw regex, and `python -m espalier` works
  as an entry point.
- **`espalier doctor` prints a one-line human verdict** (`doctor: pass/warn/fail --
  ...`) on stderr after the JSON report, so you get a bottom line without reading the
  whole report. The machine contract (JSON on stdout) is unchanged. The one verdict that
  asks you to act, saved reports differing from fresh inference, now names next steps
  instead of nothing, and a file that is not valid UTF-8 degrades instead of aborting
  the command.
- **PowerShell environment assignments are denied like their Bash twin.** `$env:VAR =
  "1"`, `Set-Item Env:\VAR` and `[Environment]::SetEnvironmentVariable` now deny with
  the same guidance the Bash form has always given, and a parity gate reports when a
  record is added to one shell's registry without a declared counterpart in the other.
- **`espalier scope-check` covers a third change surface, literal and token blast
  radius.** Declare the token under a new `## Affected literals` pack section (with an
  optional `EXCLUDE:` glob list for homonym twins) and it walks the tree, partitioning
  hits into target, excluded and ambiguous; an ambiguous hit is a scope gap (exit 2).
  Even undeclared, a literal- or path-keyed pack now draws a `[warn]` instead of exiting
  clean-looking, a literals-only pack reaches the literal arm instead of exiting early,
  and `Scope (in)` credits a path that wrapped onto a continuation line. Its
  affected-symbols reader also distinguishes an absent section from an empty one and no
  longer silently drops every declaration after the first on a multi-entry line.
- **The shipped CI workflow's pinned actions were raised:** `actions/checkout` to 7.0.1
  and `actions/setup-python` to 7.0.0, each pinned to a forty-character commit SHA with
  its version in a trailing comment; neither major version's breaking changes reach this
  workflow. Re-run `espalier install-ci` or `espalier upgrade` to pick them up.
- **The merge gate's approval marker is scoped by repo posture, and dependency-bump pull
  requests are accepted narrowly.** The marker is still required for every pull-request
  event anywhere and for a push on an adopter repo; it is no longer required for a push
  on the harness's own repository, where the pusher already holds write access. Because
  every automated dependency-bump pull request touches protected workflow paths and its
  generated title carries no marker, the gate would have failed on all of them; one is
  now accepted only when the actor, every changed path and every changed line's action
  identity all check out. The kill-switch and governance scans are untouched and still
  outrank everything.
- **`/implement-pack` and `/preflight` dispatch an orthogonal-context agent review at
  the two ship boundaries,** gated on what the diff touched. The mechanical gates prove
  a change is green; they never proved the written code was correct. Doc-only and
  test-only runs skip the review, findings are read in each agent's own severity
  vocabulary, and `/preflight`'s report must distinguish a clean review from one that
  never ran.
- **`/reflect --candidates` remembers what you skipped, and reports a skip rate.** A
  candidate you mark `skipped` in the disposition log is no longer re-proposed: each
  surfaced candidate prints a stable 12-character key to log beside the disposition, and
  the pass reports a `SUPPRESSED: N` count. Advisory and fail-open (delete the log row
  to let an insight resurface), and only the manually invoked pass suppresses. The
  report now ends with the all-time and last-20 skip rate, and the promotion pass routes
  an adopter-relevant lesson to a shipping docs reference (reachable through `/recall`)
  instead of a non-shipping local folder. The pass also suppresses a candidate you
  promoted or updated, not only one you skipped, and a fourth disposition, `held`, is
  re-proposed from the log until a decision for the same key lands.
- **The deployed hook scripts carry type annotations,** verified by a near-strict `mypy`
  gate in the harness's CI, closing a `py.typed` honesty gap where the package shipped a
  "typed" marker while running no type checker. Hook behaviour is unchanged.
- **The per-session reasoning-record prune is content-aware.** When the retention cap is
  hit it evicts empty-session stubs before nodes that carry reasoning, instead of purely
  by age. The session resume index's compaction list is capped and ordered newest first
  with an "older legs elided" line, under a label that says it spans all sessions rather
  than only the current one.
- **`espalier freshness` reads a symbol-named bound as that symbol's own lines,** so a
  `path.py::symbol` bound drifts only with the commits that changed that symbol's region
  (a nested or missing symbol falls back to the file's commit count).
  `docs/FRESHNESS.md` no longer credits the accuracy verifier with a comparison no code
  performs, says plainly that the recorded literal is compared by nothing, and names
  `espalier audit-accuracy .` as the verb that emits freshness verdicts. An existing
  `path.py::symbol` bound whose claim spans more than that symbol should be widened to
  name each symbol, or the file, and re-pinned.
- **Docs:** `docs/CHEAT-SHEET.md` carries the same "on macOS, type `python3`" note as
  the Quickstart and had been missing two commands, the README labels `docs/` as user
  and contributor documentation with a link to the documentation index, and the hook
  reference records the measured hook-latency footprint with its method, including the
  every-tenth-write case the headline figures do not describe; and every install path in
  the docs now starts with a virtual environment, since a bare `pip install` is refused
  on stock macOS and Debian (PEP 668).

### Removed

- **Breaking:** `espalier init --tier` and `--include-harness-dev` are gone, and the
  `release-verifier` agent and `verify-release` skill with them. Migration: drop those
  flags from your `init` invocation; every `init` now deploys the full surface.
- Two inert `espalier.toml` knobs that were parsed, validated and serialized but read by
  nothing are gone: `max_threads` and `preserve_existing`. Both were commented-out
  placeholders in the example `espalier.toml`, and unknown keys are ignored, so a file
  that still carries them parses as before; `preserve_existing`'s stated behaviour,
  keeping your hand-edited managed files across a re-init, is already always on through
  the managed-marker system.
- **Breaking:** three never-read keys leave the machine-readable outputs:
  `profile_scores` and `proof_gates` from `reports/harness_config.json`, and the
  always-empty `missing_path_references` slot from `espalier reflect` output. Migration:
  drop them from anything that parses those files; the reflect slot's job is already
  covered by the populated plan and manifest missing-docs siblings.
- Internal symbols reclaimed as dead weight, with no behaviour change: the `ClassInfo`
  scanner dataclass, the private `_strip_rel` and `_extract_public_symbols` helpers, the
  `stale_managed_paths` upgrade-drift primitive, the `discover_wired_hooks_by_event`
  path oracle (superseded by the executable-wiring oracle `doctor` actually calls), the
  exported-but-uncalled `copy_resource_tree` asset helper, and the write-only
  `has_docstring` field on `strengthen`'s `PublicSymbol`.

### Fixed

- **Windows and Git Bash hosts:** `rm -rf *` at the checkout root
  now meets the wall rather than the confirm-once nudge when the working directory
  arrives spelled with backslashes, and a `cd "/c/Users/..."` step is read as the
  drive path Git Bash means, so a protected write after it is refused instead of
  waved through. A symlink loop at `.claude` is reported as a loop on every host
  instead of read as a missing directory, and the hooks that print content write
  UTF-8 on both streams, so a non-ASCII byte no longer empties a captured stream on
  Windows.
- **`write_guard`, recursive deletes:** a recursive delete without a force flag now
  meets the same refusal the forced spelling meets. `rm -r /`, `rm -r ~`, `rm -r .`, `rm
  -r *` from the checkout root and the stray-space typo `rm -r ~/ build` previously drew
  nothing at all; recursion alone is now the threshold on both shells, and PowerShell's
  `Remove-Item -Recurse` without `-Force` refuses a catastrophic target and draws one
  confirm-by-re-issue nudge on anything else. The delete checks also judge a command
  with its same-line literal bindings inlined, so `X=/; rm -rf $X` refuses where it used
  to nudge.
- **`write_guard`, what counts as catastrophic:** the target is judged by meaning rather
  than by its first character. The filesystem root, `$HOME`, the repository itself, a
  shallow system path, an unbounded leading glob and an absolute `..` step are refused;
  a bounded glob, a temp root and a repo-internal build directory fall to the
  confirm-once nudge instead. Both deny texts, `docs/HOOKS.md` and `docs/SHARP_EDGES.md`
  now describe the rule the code enforces.
- **`write_guard`, clearing a build directory from inside it:** a bare leading glob or
  `$PWD` is judged as the directory its statement runs in only when the command is plain
  (statements joined by `;`, `&&`, `||` or newlines, with no pipe, group, subshell,
  substitution, heredoc, loop, background job or program handed to another shell). That
  everyday clean draws the nudge; a clear that lands on the checkout, the home directory
  or the filesystem root still refuses.
- **`write_guard`, `find` with a delete action:** `find . -delete`, the rootless `find
  -delete` and `find . -exec rm -rf {} +` from the checkout root previously passed every
  check. An un-narrowed `find` with a delete action now goes through the same classifier
  as `rm`. Narrowing is a name-or-path predicate in force before the action; `-type`,
  `-size`, `-perm`, `-mtime` and `-user` do not narrow, and a negation or `-o` re-widens
  the walk.
- **`write_guard`, sweeps whose targets arrive indirectly:** an enumerator piped into a
  remove verb (`find . | xargs rm -rf`, `ls | xargs`, `git ls-files | xargs`), a `for`
  loop over a bare word list or glob (`for f in *; do rm -rf "$f"; done`), and a read
  loop fed by a command or process substitution are now read on both the Bash and the
  PowerShell tool, with the enumerator's roots judged as the remove verb's operands. A
  narrowing predicate narrows by its value, and a bounded pathspec or wildcard still
  narrows a `git ls-files` sweep.
- **`write_guard`, discovered commands:** a verb the shell resolves at runtime is read
  as the verb it names: `$(which find)`, `"$(command -v rm)"`, the backtick form, zsh's
  `$(whence ...)` and `=find`, and PowerShell's `& (Get-Command find)`, `& (gcm ri)`,
  the dot-source operator and an object's `.Source` member.
- **`write_guard`, PowerShell sweeps:** the recurse and force switches are read by every
  spelling that runs (unambiguous cmdlet prefixes, long forms, and `/bin/rm` clusters
  with bash's rule that an `i` after the last `f` cancels force), so `ri -r -fo C:\` and
  `rm -rf ~` are no longer silent. A rootless enumerator pipeline (`gci -Recurse | ri`)
  is judged by the directory it runs in, `-Attributes !Directory` is read as a
  files-only walk, the recursive .NET directory delete is read as a wipe, and `unlink`,
  `shred`, `truncate` and `git clean` reach the protected-zone check there as they do on
  Bash.
- **`write_guard`, discard snapshot:** a recursive delete of a directory holding
  uncommitted tracked edits now takes a `git stash create` snapshot before the nudge,
  loop spellings included, and logs the object id with its command to
  `cc/discard_snapshots.log` (recover with `git show <sha>:<path>`). The nudge claims a
  snapshot only when one was actually taken; an untracked, clean or out-of-repo target,
  and a delete that takes the snapshot's own store, keep the honest no-recovery wording.
- **`write_guard`, protected-zone writes on the PowerShell tool:** `Copy-Item` and
  `Move-Item` with their aliases, the Windows permission verbs `icacls`, `cacls`,
  `takeown`, `attrib`, `Set-Acl` and `Set-ItemProperty`, the .NET static file API
  (`[IO.File]::WriteAllText`, `::Copy`, `::Move`, `::Replace`, `::Delete`,
  `[IO.Directory]::Delete`), `cipher /e|/d`, and the property-assignment form `(Get-Item
  <hook>).IsReadOnly = $true` are all denied there now, as their Bash twins are.
- **`write_guard`, permission verbs on Bash:** `chflags`, `chattr` and `setfacl` on a
  protected path deny like `chmod` does, and so do the macOS `chmod -E`, `-N` and `-I`
  forms that carry no mode token.
- **`write_guard`, in-place edits and write-verb option grammars:** the BSD and macOS
  spelling of an in-place edit (`sed -i ''`), the glued `-i.bak`, `--in-place=.bak`,
  bundled pre-flags and multi-target invocations now reach the protected-zone check
  through a tokenizer rather than one regex, and `perl -i` gained an extractor of its
  own with its own option profile. Alongside: `cp --force` and the other long flags,
  `patch` writing its *first* positional, multi-source `cp` and `mv` where the
  destination is the last positional, `-t` and `--target-directory` in their abbreviated
  and glued forms, and `--` ending option parsing.
- **`write_guard`, interpreter programs:** the literal write paths inside a program
  handed to an interpreter are read on both the Bash and the PowerShell tool: `-c` and
  `-e` inline, a program piped into the interpreter, and the `py` launcher, plus on Bash
  a heredoc on stdin (`python3 - <<'PY'`); PowerShell has no heredoc. A shell-out from
  inside such a program (Python's `os.system` and `subprocess`, Perl's `system`,
  backticks and `qx`, node's `child_process`, Ruby's `system`, `%x` and `Open3`, awk's
  `system` and print-into-command, GNU sed's `e`, and git's alias, credential-helper and
  exec-valued config doors) is scanned as a program of its own one level down.
- **`write_guard`, operand spans:** an operand span no longer runs past a newline, so a
  following line can neither displace a destination nor be read as one; a backslash
  continuation is spliced first; a redirect operator and its target are skipped, glued
  or spaced, including the `&` of `2>&1` written before the target; a same-line `#`
  comment ends the span; and a quoted path containing a space is read whole through one
  shared operand tokenizer.
- **`write_guard`, cross-shell programs:** a program handed to the other shell is judged
  by that shell's grammar rather than by the tool it arrived on. `powershell -Command
  "..."` and `pwsh -c "..."` on the Bash tool go to the PowerShell readers, and `bash
  -c` or `sh -c` on the PowerShell tool to the Bash ones, one level down and
  depth-bounded. `-EncodedCommand`, `-File`, a program held in a variable, a program
  piped to `-Command -`, `wsl bash -c` and `cmd /c` remain stated limits.
- **`write_guard`, PowerShell payloads behind a wrapper:** a double-quoted program
  handed to a re-parser keeps its statement separators, so the second statement of
  `powershell -Command "cd x; <recursive delete>"`, of `iex "...; ..."` and of the
  here-string forms now meets the same check as the single-quoted twin. The switch run
  that reaches a wrapper's quoted payload now carries one bare value per switch, so
  `-Verb RunAs`, `-ExecutionPolicy Bypass` and `-WindowStyle Hidden` no longer hide what
  follows them. A quoted value, an `=`-bound value and the array spelling of
  `-ArgumentList` are stated limits.
- **`write_guard`, PowerShell path spellings:** `$env:CLAUDE_PROJECT_DIR/`,
  `${env:CLAUDE_PROJECT_DIR}/` and the `$($env:CLAUDE_PROJECT_DIR)` subexpression are
  stripped like the Bash spellings; a literal value bound to a variable earlier on the
  line is inlined before the scan; and a backtick line continuation is joined at every
  PowerShell entry point, so a path split across lines is read whole.
- **`write_guard`, Windows path normalisation:** the Git Bash drive spelling
  (`/c/Users/...`, which is what `pwd` returns there) is translated to its Windows form
  on Windows: on the target, on the `CLAUDE_PROJECT_DIR` value the root comes from, and
  inside the POSIX comparison, so the protected zones and the plan check see the same
  path. `~` is now expanded before separators are folded.
- **`write_guard` and `plan_guard`, git worktrees:** a session that enters a git
  worktree of the repository keeps `CLAUDE_PROJECT_DIR` at the project root, so every
  path under the worktree used to read as unprotected and plan-exempt. Both guards now
  relativise against the deepest checkout containing the target, denials name it, and
  the SessionStart line says a worktree is governed.
- **`write_guard`, secret-path reads:** the read-verb roster is applied on the
  PowerShell tool too (`Get-Content .env`, `gc`, `type`, and any executable on PATH such
  as `head -5 .env`), read with PowerShell's own separator set. A template name ending
  in `.example`, `.sample`, `.template` or `.dist` is exempt on every channel, a
  copier's destination is a write rather than a read (so `cp .env.example .env` passes),
  a `#` that starts a token ends the operands, and the dotenv name alone is compared
  case-folded.
- **`write_guard`, read-only commands:** its write verbs matched anywhere in a command
  string, so a `grep` whose search pattern contained `install`, `rsync`, `truncate`,
  `patch` or `tee` against a governed directory was read as a write there, as were flag
  clusters like `ls -cp`. The verbs now anchor at a command position (start of input,
  after a separator, behind a wrapper such as `sudo`, `env`, `time` or `xargs`, after a
  shell keyword, or inside a shell-exec quote), and further routes found afterwards
  (carriage return, a `case` arm, vertical tab, a leading redirection, `setsid`,
  `strace`, `watch`, `script -c`, `\cp`, `$'cp'`) are closed. The same anchoring fixed
  three git path patterns on the hard-deny side that refused a read-only search
  outright.
- **`write_guard`, prose about the guard:** the checks that used to refuse ordinary text
  now anchor on a command position and read a masked command. Fixed: the inline
  interpreter openers matching a mention in a `#` comment or a quoted string; `then`,
  `do`, `else` and `elif` matching anywhere; `export` and `declare` matched by a bare
  word boundary; an assignment word whose quoted value names a delete or a protected
  write; a quoted search pattern carrying `\|` manufacturing a phantom `cat` statement;
  `-ln` and `-cp` *flags* read as `ln` and `cp` commands; shell variables named after a
  write verb (`rm=$(...)`, `install=$(...)`); a comment or trailing token naming a
  protected path beside an ordinary `chmod`, `sed -i`, `install`, `rsync` or `patch`;
  and a quoted note beside an interpreter call.
- **`write_guard`, command cost:** several inputs used to cost more than the hook's
  timeout, so that no verdict reached Claude Code at all, and because a wedged regex is
  neither an exception nor a refusal the tool call simply never returned. A shared
  fragment that decides whether a verb sits at a command position backtracked
  catastrophically on a repeated command prefix (`eval `, `sh -c `, `env -i `, `nice -n
  10 `, `xargs -0 `, `strace -f `), taking over five seconds at thirty repetitions and
  growing from there; two more patterns were quadratic on a separator-dense command; and
  a long run of unmatched grouping characters, a flood of PowerShell switch pairs or
  quoted literals, a flood of piped interpreter openers, and an ordinary Windows
  argument such as `c:/my-dir/run.ps1` behind a valued switch each took seconds. All now
  return promptly. Accept and reject behaviour is unchanged but for one declared limit:
  the PowerShell masker's re-parse lookback is bounded to 2 KB, so a literal further
  than that from its re-parser reads as a mention.
- **`write_guard`, maintenance-mode prefix:** `ESPALIER_MAINTENANCE_MODE=1 pytest -q`
  and `ESPALIER_MAINTENANCE_MODE=1 python3 <hook>`, the edit-then-run loop maintenance
  mode exists for, are allowed again. Launching `claude` with one of those variables is
  still denied, now matched by basename across wrapper words rather than on the first
  word only, with every occurrence in the command judged rather than the first, and with
  `export VAR=1; claude` and `declare -x` covered. The same over-blocking on the
  PowerShell leg is fixed the same way.
- **Speed-bump checkpoints:** every irreversible checkpoint is keyed per invocation, so
  a read-only command that merely quotes a dangerous spelling no longer retires the
  checkpoint for the rest of the session. `CP-GATEWEAKEN` now reads its pre-image from
  disk, so a full-file `Write` over a guard file fires where it used to be silent.
  `CP-DISCARD` covers a bare `git checkout <path>`, firing only when that path is
  actually dirty and staying silent on a branch switch. `CP-RELEASE`'s release arm is
  anchored and consumes `gh`'s global options. The git verbs also anchor at a command
  position, so a `grep` for a destructive git form, an `echo` of a warning or a `#`
  comment no longer nudges at all, where each once re-nudged on every distinct mention.
- **Relaunch hints:** the maintenance-mode relaunch line the deny messages and the docs
  print is now host-keyed (PowerShell, `cmd.exe` and Git Bash forms on Windows) and
  carries `--continue`, so pasting it no longer starts a fresh conversation or fails to
  parse. The hook layer spells it once and both deny templates route through it.
- **`plan_guard`:** `memory/`, `docs/`, `task-packs/` and `.espalier-state/` are exempt,
  because the harness's own commands instruct writes there at moments when no plan is
  active. Root-level source in six more languages (`.rb`, `.php`, `.cs`, `.swift`,
  `.kt`, `.scala`) is plan-gated, from one language set shared with the reflect tracker.
  A flat-layout repository can now exempt root-level source with `plan_exempt_prefixes =
  ["./"]`, and the deny message names that escape hatch when it fires there.
- **`stop_gate`:** Gate 3 is satisfied by a review actually running rather than by one
  having been requested. `subagent_stop` writes `.espalier-state/code_reviewed` when the
  `code-reviewer` agent finishes, and the gate re-arms until that record exists. The
  docs gate reads the changed markdown paths the record carries, so an agent that wrote
  nothing no longer clears it. Either gate can be relieved by a record you write by hand
  with a note saying why, and the relief is announced on stderr so the transcript shows
  it. Each gate block now writes an audit record.
- **`stop_gate`, the mode setting:** five readers parsed the value five ways, so a
  space-padded setting ran the full test suite on every stop while the status line
  showed no indicator. One shared normalization now backs all of them.
- **`stop_gate`, the test-command override on Windows:** it was split with POSIX quoting
  rules on every platform, and those treat a backslash as an escape, so an ordinary
  interpreter path was rewritten into one that cannot exist, the override never ran and
  the hook returned nothing where a decision was contracted. It now splits with the
  host's own rules while still honouring quoted arguments. Separately, test-runner flags
  that consume the following token no longer leak that token as a file path, including
  the worker-count flag; one of them had inverted a deselect into a select.
- **`session_start`:** the banner carries an `Integrity:` line beside `Surface:`, so
  drift the hook already detected reaches the session instead of only stderr; a clean
  state is rendered explicitly so `ok` and no line at all cannot look alike, and a
  verification that raised reports `unverified`. The `Memory:` digest filters whole
  template lines instead of anything that merely opens like one, so your own text
  survives. A plan left `in_progress` is named in an `OPEN PLAN` section on a fresh
  session. On POSIX a `Loose:` line names orphaned heavy-CPU `python*` and `yes`
  processes by PID, reporter only. The nested-repository warning no longer names the
  worktree the session is running in, or a worktree git holds a lock on; a session
  inside a nested repository gets one informational line instead. The banner no longer
  warns that `ruff` is missing on a plain `pip install`; ruff ships only in the
  harness's own dev extras, so the warning named a tool an adopter is not expected to
  have.
- **`config_guard` and `ci_guard`:** an empty top-level hook list for an event Espalier
  does not govern (your own `"PreCompact": []`) is ordinary configuration, not a kill
  switch. Only an empty list for a governed event is flagged, matching the in-session
  integrity check, and the governed-event set is pinned equal across the three copies
  that must agree.
- **CI workflow template, job creation (breaking on upgrade):** the workflow 0.8.0a13
  shipped gated three jobs on a job-level `hashFiles()` expression, which GitHub rejects
  at parse time, so the file created zero jobs and the adopter-facing verify job never
  ran. The gate moved into a `detect-source` job whose outputs the others read.
  **Upgrading:** re-run `espalier install-ci` and merge the parked `.new` workflow over
  yours.
- **CI workflow template, approval binding (breaking on upgrade):** the `harness-guard`
  marker must now name the head under review, `HARNESS-UPDATE-APPROVED@<sha>`, so a
  force-push after approval goes red instead of riding an unchanged pull-request title.
  The shipped workflow forwards `PR_HEAD_SHA` and lists `edited` among its activity
  types; a pull-request run whose `PR_HEAD_SHA` is missing or not commit-shaped fails
  closed and prints the exact env line to add. **Upgrading:** `espalier install-ci`
  rewrites `tools/cc/ci_guard.py` but parks a differing workflow as
  `.github/workflows/harness-guard.yml.new` and warns by name when yours lacks the
  forward; merge it over yours, commit both together, and re-title any open pull request
  carrying a bare marker.
- **CI workflow template, default branch:** a repository whose default branch is not the
  conventional one now gets push-time enforcement. The diff base is taken from the
  repository's real default branch, forwarded from the event payload, before falling
  back to the historical pair. Widening the branch filter alone would have rejected that
  population's first push, whose event carries no previous ref, so the diff base fell
  through to the initial commit and every protected path read as changed.
- **`install-ci`, CRLF workflows:** A Windows adopter whose committed YAML came back
  from git as CRLF got "exists and differs from espalier's", a littered `.new` file and
  a merge gate reported inactive, for a byte-identical workflow.
- **`/status --log`:** every denial the PreToolUse and ConfigChange hooks make now
  reaches the reader, including the secret-path read deny (logged under a type nothing
  read) and the speed-bump fire (never written at all). Records are filtered to the
  checkout you asked about rather than shared by basename between two checkouts of the
  same name. Refusals and once-then-continue pauses are counted separately, with the
  day's pause count on its own line and `--log N --all` widening the tail to them.
  `--log <repo>` no longer dies with `invalid int value`, and a path that is not there
  is a usage error rather than a confident "no denials". A day on which maintenance mode
  switched a check off is no longer reported as a clean day: `write_guard`, `plan_guard`
  and `stop_gate` each write one advisory record per session. Each hook's crash guard
  writes a typed record before it emits, so a wedged hook that denied every call is
  visible after the fact.
- **`init`, `.gitignore`:** `reports/` is written root-anchored, because git floats a
  single-segment pattern to every depth and an adopter's own `src/analytics/reports/`
  was having new files silently dropped from `git add -A`. Entries are also checked
  against what the repository already tracks: where the pattern's target *is* a tracked
  path the entry is withheld, named, and paired with the `git rm -r --cached` that hands
  the path over; where it is a directory you co-occupy the entry is written and the one
  real consequence stated. Coverage is now git's own answer rather than a string
  compare, so a tree carrying `*.py[cod]` is no longer told forever that `*.pyc` is
  missing, and a root-anchored spelling of an any-depth entry is correctly reported as
  not covering. The required entries grew from five to twelve: `/task-packs/`,
  `cc/_working_summary.md`, `__pycache__/`, `*.pyc`, `.claude/*.new`, `.claude/*.bak`,
  `.claude/*.bak.*` and `cc/_cold/` join `.claude/settings.json`, `.espalier/`,
  `.espalier-state/`, `/reports/` and `cc/blueprints/`, and `upgrade` writes the block
  before its "harness is current" early return.
- **`init`, an unappendable `.gitignore`:** A `.gitignore` that could not be appended to
  (a dangling symlink into a dotfiles directory, or a directory in its place) aborted
  with a bare errno after every file was deployed and every hook wired, so the success
  banner never printed and each re-run failed identically. It now degrades to the same
  warning the opt-out flag prints, naming the entries to add by hand.
- **`init`, interpreter detection:** a host whose only `python` is a Python 2 shim is no
  longer wired as "a below-floor Python 3" under a banner claiming the guards are live.
  Every hook there exited 0 without a decision, so every guard failed open. The floor
  gate and its warning twin now ask whether the banner is a Python 3 banner, `doctor`
  probes the identity of each interpreter word a wired entry runs under and blocks the
  enforcement claim when one does not answer as Python 3, and the warning quotes the
  first candidate that answered rather than the last. Where the resolver's own answer
  fails the floor, every printed remedy spells an interpreter that can actually run it.
- **`init`, the wire prompt:** Ctrl+C at `Wire them now?` ends with one sentence and
  exit 130 instead of a traceback over a half-installed repository, after saying what is
  deployed and naming the verb that finishes (`init . --wire-hooks`). Ctrl+D (Ctrl+Z,
  Enter on Windows) is the default No, and a fully closed stdin degrades to the
  non-interactive preserve-and-warn default instead of raising.
- **`init`, the generated `CLAUDE.md`:** the sections hook denials tell you to read are
  now always rendered. `## Maintenance mode` did not exist on any adopter tree while the
  protected-zone deny cited it; `## Plan Guard` was gated on a truthy fingerprint
  pattern and skipped entirely when you already owned a `CLAUDE.md`; and `##
  Cross-platform Python invocation` was cited by a seeded doc and never rendered. `init`
  and `upgrade` now name a preserved `CLAUDE.md` by filename, say which cited sections
  it lacks, and point at `render-template claude`.
- **`init`, statusline on Windows:** the shell fallback that prints `espalier:
  statusline did not run` could not be written for Windows PowerShell 5.1, so a broken
  interpreter blanked the statusline with no explanation. A deployed batch shim,
  `tools/cc/statusline.cmd`, carries the fallback there and is wired as the head of
  `statusLine.command` with the interpreter as its argument; `--rewire-interpreter`
  swaps the argument and never the head, and the uninstall drops a shim-headed
  `statusLine` with the shim it deletes.
- **`init`, statusline path quoting:** the generated command quotes the project path, so
  a directory containing a space is no longer split and truncated.
- **`init`, seed documents:** the seeded convention docs used to be skip-if-exists, so
  an untouched copy kept stale bytes across every upgrade. They now carry a first-line
  `espalier:seed-version` stamp and are refreshed on re-init only while they still match
  the copy they were deployed from; an edited or unstamped copy is left as you left it.
  Every doc, README and command body that said "never overwritten on re-init" now states
  that rule, `upgrade` re-runs the seed deploy, and `doctor` prints a lost stamp for you
  to paste back instead of sending you to `git show`.
- **Settings merge (`init --wire-hooks`, `fuse --wire-hooks`, `merge-settings`, `upgrade
  --execute`):** the merge now adds espalier's `statusLine` when the key is absent (a
  present key of any value, an explicit `null` included, is yours and is never
  rewritten), reports which profile allow rules your file lacks, and appends them on
  `merge-settings --add-allows` after your own, never removing one, never re-adding one
  you denied or set to ask, and never touching the deny list. A `settings.json` that is
  empty after any byte-order mark is rewritten in place. The three paths that rewrite
  your `settings.json` now reuse an existing `.bak` rung already holding the exact
  bytes, so repeated wire/uninstall/wire cycles stop leaving byte-identical `.bak.1` and
  `.bak.2` copies. `doctor`, the `init` banner and the `fuse` banner no longer offer
  `merge-settings` on a file the merge would refuse.
- **`merge-settings --repair`:** a dead hook entry, one running no interpreter, missing
  from an event that exists, sitting under the wrong event or with a narrowed matcher,
  or still in the pre-0.6.5 shell form, now has a command instead of a hand edit. It
  rewrites only entries naming espalier's own scripts, matched as whole path tokens by
  basename, keeps your own entries and their matchers, lists every entry it removes by
  command, writes a `.bak` first, and re-derives the wiring afterwards naming anything
  still dead.
- **Wiring oracle:** the check behind `doctor`'s governance verdict and `init`'s "Hooks
  now intercept" claim was pinned to the four blocking gates, leaving the eight reporter
  hooks outside every check. `doctor` now warns per deployed reporter with no executable
  wiring, naming its event, its job and the remedy for its shape; matcher coverage
  checks every token of the canonical matcher rather than three tool names; and an entry
  under the wrong event or with a narrowed matcher is reported as miswired rather than
  forgiven as the legacy shell form. Warnings, not failures.
- **`upgrade`:** a version stamp matching the engine no longer short-circuits to
  "harness is current; nothing to do" over a hook altered by one appended line, a deploy
  weeks behind an engine whose version never moved, or a saved plan listing a retired
  agent. `upgrade` now consults the packaged surface and the saved plan through the same
  compares the deploy writes with, names each drift class in the preview with what
  `--execute` does about it, and re-baselines the fingerprint so `doctor` agrees with
  `upgrade` afterwards. A tree with no saved plan is told the plan was not compared; a
  managed file you edited and un-marked is named as kept rather than as drift.
- **`doctor`:** on a tree emptied by `clean-generated --execute` it reports the tree as
  uninstalled and offers the reinstall command, instead of "missing required managed
  surface" with every removed hook listed as a stale plan path; once the runtime state
  is gone it reports the tree as never initialized. A recommended agent with no packaged
  body is no longer a stale saved-plan path. The managed-surface gate stands down where
  the audit already does and names itself for the tree it ran on. A missing `ruff` no
  longer degrades a `pip install` adopter's headline status to `warn`. One missing
  command is reported once rather than twice, and the recovery assessor's finding is
  named on one line.
- **`integrity`:** the manifest now hashes a canonical text form (`sha256-lf`: a leading
  byte-order mark stripped, CRLF and bare CR folded to LF), so a checkout git re-ended
  to CRLF, the default on Git for Windows, no longer reports every managed file as
  changed out of band, with `refresh` re-pinning to CRLF and the next LF checkout
  flipping them all back. The legacy raw-bytes algorithm still verifies raw until the
  next refresh, and `integrity verify` reports the algorithm in use.
- **`integrity`, a corrupt manifest:** verification now fails on it instead of reporting
  healthy. The loader returned the same empty answer for a manifest that was absent and
  one that was truncated, not an object, unreadable or replaced with a symlink, and the
  exemption that correctly forgives an absent manifest forgave the rest, so a repo whose
  tamper detection was blind reported healthy and exit 0. Absent and unusable are now
  separate signals and only absent is exempt; the diagnostic names the corruption
  instead of reusing the drift wording. Migration: if verification now reports an
  unusable manifest, run `espalier integrity refresh`.
- **`audit`, `integrity verify` and `recover` on a fresh tree:** a source checkout or a
  never-initialized repository now exits 0 with "run `espalier init .` first" instead of
  a red failure, a `DEGRADED` surface verdict, or a hard failure over a gitignored
  per-install manifest that is simply absent. An initialized surface that is genuinely
  broken, or an initialized repository whose manifest was removed, still fails.
- **`freshness check` no longer dirties the working tree.** It wrote a derived
  `state_cache` block with a fresh timestamp into the committed
  `.espalier/freshness.json` on every run, so a read-sounding command contaminated any
  commit staged after it and conflicted a stash or rebase. The derived cache now lives
  in its own gitignored per-install file, `.espalier/.freshness_state_cache.json`, and
  an upgraded checkout self-heals on the next pin.
- **`freshness pin`:** a pin no longer vouches for a verification HEAD does not back. A
  pin taken with a bound path edited but uncommitted is refused without `--force` and
  names the paths, a scan reads an uncommitted bound as `stale` (never `critical` on
  that ground alone) with the paths in a new `dirty_paths` field, and `pin --all`
  refuses before pinning anything so a cohort re-attestation resets together or not at
  all. A pin given no `--expected-value` now carries the entry's own literal when
  nothing moved under it, retires it when the policy no longer takes one, and refuses
  when commits since the pin touched the bound or the literal was edited by hand. `pin
  --all <repo>` no longer runs on the current directory, which happened because the
  optional fragment id swallowed the path.
- **`freshness`, day axis and counting:** a warning band now stands between fresh and
  critical, so a cohort pinned on one date gets a fortnight of notice rather than going
  from all-green to blocking overnight, and the check reports when one date dominates
  the manifest. A fragment bound to several symbols in the same file counts that file's
  commits once rather than once per symbol, so an honestly fresh fragment can no longer
  be pushed to a false `critical` that blocks a merge.
- **`fingerprint`:** the walker did not skip the type-checker caches its sibling scanner
  already skipped, and a database was reported with a fabricated line count because the
  reader decoded with replacement characters. Large files are now content-sniffed.
- **`scan`, robustness on an adopter tree:** a single unreadable `.py` (a dangling
  symlink, a permission-denied file, a file deleted mid-walk) no longer aborts the run
  having written no reports. Each scanner skips the file, records it under a `skipped`
  key, and keeps going, and `scan` prints one warning naming how many files were
  skipped. Every scanner walk now prunes an embedded git repository, so a vendored
  dependency's code is not flagged as yours. `scan` also names the report file behind
  each non-empty finding count instead of printing counts alone.
- **Scanner false positives:** the harness-internal scanners (subprocess and filesystem
  contracts, magic depth, retired vocabulary, encoding contracts) stay silent outside
  the harness's own tree, several matchers ignore strings and comments, and
  `/scope-check` matches on word boundaries, so `main` no longer matches `maintain`.
  Also: an `async def` test whose proof is an `await` or `async with` body is a real
  test; a handler logging through an inline `logging.getLogger(__name__)` or a
  snake_case `get_logger()` receiver such as `structlog` is logging, not a swallow; a
  method named `open` is not a bare `open()` call; a test that mentions a decision
  channel only inside an assert message, a `raise`, a `print()` or a `pytest.fail()`
  argument is still reported as non-discriminating; and the freshness scanner's
  bound-closure walker now resolves relative imports and a module imported by name from
  its parent package.
- **Decoding, engine-wide:** a text-mode subprocess capture and a strict text-file read
  raise `UnicodeDecodeError`, which is a `ValueError` and slipped past every `except
  OSError` handler. A repository holding a filename git prints in a non-UTF-8 encoding
  produced a traceback from `doctor`, `audit` and `init` on an otherwise healthy tree; a
  `cc/COMMANDS.md` re-saved in a Windows code page cost you the SessionStart banner and
  blocked every Stop under `ESPALIER_STOP_GATE=full`; and a `cc/GOAL.md` or
  `ESPALIER_MEMORY.md` written as UTF-16 with a byte-order mark by Windows PowerShell
  crashed the reader. Reads whose content is names, lines or sentences now decode with
  `errors="replace"` and catch `ValueError`; reads whose content is a structured answer
  such as a version banner or a SHA stay strict and catch it too, so a corrupted answer
  takes the failure path rather than being masked by a replacement character. A
  pre-existing managed `cc/` document or `.md` asset that `init` cannot decode is
  preserved byte-for-byte and reported as skipped instead of aborting the install.
- **`clean-generated` (uninstall):** the report now accounts for every file the verb
  leaves behind. It names the surviving path that keeps each retained `.gitignore`
  entry, retires the entries nothing needs any more (block-delimited, with lines outside
  the block never read), lists the `settings.json` backups it leaves, names a `.bak` as
  a preserved user file, deletes the `__pycache__` directories under `tools/cc/`,
  finishes the settings unwire (the `statusLine` that ran the deleted script, the
  managed sentinel and an emptied `hooks` key), previews the strip in the dry run, and
  accounts for the three artifacts `install-ci` writes. The `TROUBLESHOOTING.md` and
  `QUICKSTART.md` uninstall sections no longer claim it deletes files it deliberately
  preserves.
- **`fuse`, non-editable installs:** it refuses instead of half-building and then
  blaming `init`. It overlays by reading the source tree, which a wheel does not have,
  so it exited 1 after leaving a partial fusion on disk; it now refuses before doing any
  work, naming the install mode it cannot support and the supported alternative. The
  fusion summary line is also derived from what was actually copied rather than naming
  four fixed categories.
- **`fuse`:** its two rollbacks no longer silently under-delete and leave a partial
  fusion that the retry then refuses; a git repository that tracks nothing is no longer
  treated as one that tracks something (a host inited but never committed produced a
  fusion containing none of your source at exit 0); the epilogue reads whether the CI
  workflow is tracked instead of asserting a commit it never made; its
  `docs/SHARP_EDGES.md` stub is stamped the way `init` stamps a seed; the start-here
  line prints exactly once, at the end, with a quoted path to change into; and the
  maintenance-mode relaunch is printed with the `cd` above it.
- **Rendered surface documents:** the seam that rewrites the saved plan after `init`
  refreshed the plan but not `cc/LIVE_SURFACE.md` and `cc/COMMANDS.md`, so a tree could
  report two surface docs rendering differently seconds after it was built. Both are
  re-rendered through the same classifier `init` and `upgrade` use, a byte-identical
  render is untouched, an unmarked doc is left as yours, and `upgrade`'s preview
  predicts the re-render so preview and execute name the same files.
  `cc/LIVE_SURFACE.md` also lists `.claude/skills/` entries in a `## Skills` section; it
  had discovered agents, commands and hooks and silently omitted an entire invocable
  surface class.
- **Managed markers, empty frontmatter:** with `---` immediately followed by `---`, the
  managed marker was inserted above the opening delimiter, invalidating the block, or
  glued onto the closing one.
- **`scope-check` and the pack parsers:** a bullet struck with `~~` under `## Affected
  symbols` or `## Affected literals` is no longer collected and walked; a `Scope (in)`
  written as a numbered list is read, where ordered items were never opened as bullets,
  so such packs declared no files and every symbol reference came back as a gap; the
  bare none spellings (`- None.`, `- _None._`, `- (No new files ...)`) are recognised as
  declared nothing; and a declaration is the first backticked token outside an
  annotation, so a parenthesised aside no longer declares a path. A section that
  declares a blast radius but parses to nothing now prints `scope-check:
  DECLARED_BUT_EMPTY` instead of sharing its wording with a pack that has nothing to
  walk, the empty-parse message names its real cause, and the summary reports the
  heading it matched.
- **`scope-check`, report order:** the reference walker's faster backend searches files
  in parallel and returned matches in whatever order its threads finished, while the
  other backend returned them sorted, so the same repository could produce differently
  ordered reports on consecutive runs and a report was unusable as a diff. Both fast
  paths now impose a file-and-line order.
- **`surface-impact`:** a path a pack *removes* now reports the same obligations its
  addition would, through one shared classifier, with a leading line saying what reverse
  means; a path-shaped `### Renamed` entry is read as a removal of the old name. An
  ambiguous top-level token whose suffix it does not recognise (`go.mod`,
  `configure.ac`) is warned about rather than dropped, dotfiles and `.cfg` and `.ini`
  files are admitted as paths, and a prose method token such as `.strip()` is excluded.
  The `provenance` obligation, which cannot be discharged off the Espalier source tree,
  is dropped there, and the report carries a footer naming what it withheld rather than
  shortening itself in silence.
- **`sister_site_probe.py` on an adopter tree:** the probe scanned only the deployed
  hooks and the engine, so an adopter's first `/implement-pack` step went red on the
  harness's own debt inside files `write_guard` forbids them from editing, while a
  duplicate under their own `src/` was never seen. It now scopes to your own source
  roots (`--roots` names them), reports the harness's debt as an advisory, and its
  `--json` shape changed with it.
- **Advisory hooks:** `post_write_check` validated agent and command bodies but never a
  skill body, and now checks all three kinds; it also derives the written paths of a
  Bash or PowerShell edit with the guard's own extractors, so a heredoc, `printf >>` or
  `sed -i` edit triggers the same edit-time advisories a `Write` does. `subagent_stop`
  records the lead of the subagent's own final message with its transcript path as
  evidence, rather than a fixed sentence, and is wrapped in the same fail-open crash
  umbrella its siblings carry, so an uncaught error becomes one stderr line and exit 0
  rather than a traceback Claude Code reads as a failed event. The UserPromptSubmit hook
  no longer prints its unset-`CLAUDE_PROJECT_DIR` fallback warning twice per prompt.
- **`reflect_trigger`:** that counter gates the Stop check for significant changes that
  may need doc updates, so a session whose tracked source had not changed at all could
  be blocked by scratch writes outside the root.
- **Atomic writes, file modes and links:** every file the harness rewrites kept its
  content and lost its mode. The tempfile-and-replace took its tempfile from `mkstemp`,
  which hardcodes 0600, so a fresh file landed 0600 where `open()` gives 0644, an
  existing 0644 file became 0600 after one write, and a 0755 hook script lost its exec
  bit. A checkout shared with another OS user or a CI cache running as one found
  harness-written files unreadable, and a `chmod +x` was undone by the next init,
  upgrade or session. The writer now creates at 0666 under the umask and copies an
  existing regular target's mode onto the tempfile before the replace; files an earlier
  release wrote at 0600 keep 0600 until changed once. On a shared box set `umask 077` if
  that matters. On a symlinked target the rule is decided per target: harness state
  files are replaced with a regular file, while your own `.gitignore` and
  `settings.json` are edited behind the link and keep it. A hardlinked target is still
  severed, and the mode leg is a no-op on Windows.
- **Windows and cross-platform:** a read-only file, which is every packfile git writes,
  no longer stops the harness's tree and file removals; one shared remove helper clears
  the write bit and retries once on what it was asked to delete. Every path the engine,
  the hooks and the scanners name in a message is spelled as a path rather than through
  `repr`, so a Windows path in a failure message can be pasted into a shell.
  Finding-detail paths in the managed-surface gate, and broken-link paths in the reflect
  report, are normalized to forward slashes. Recursive walks no longer crash with
  `OSError(ELOOP)` on Python 3.10 through 3.12 in a repository containing a
  directory-symlink loop. And a `.claude` whose parent denies traversal gives one
  verdict on every supported interpreter, "unreadable, resolve its permissions", instead
  of `doctor` listing every deployed file as missing on 3.14 and dying with a bare
  `[Errno 13]` on 3.10 through 3.13.
- **CLI, uniform behaviour:** every repo-scoped command rejects a nonexistent `--repo`
  path with the same message and exit code, instead of leaking `[Errno 2]`, scaffolding
  a phantom tree, or reporting "clean". A mistyped subcommand lists only the public
  commands `--help` shows. The `freshness` and `memory` required-argument errors render
  `{check,pin,unpin}` and `{prune}` rather than an internal argument name. Three verbs
  the README documents were registered without help text and are now listed by `--help`.
  Count messages across the engine are pluralized (`1 warning`, not `1 warning(s)`), and
  `init`'s ownership tally now sums to its `Deployed: N files` headline.
  `refresh-externals --interactive` exits cleanly without a usable stdin, and one
  malformed pin URL degrades to a recorded fetch error rather than aborting the batch.
- **Interpreter in printed hints:** every runtime hint the engine prints or returns now
  threads the detected interpreter rather than a hard-coded `python -m espalier ...`, so
  on a host shipping only `python3` (stock macOS) or only `python` (Windows) the first
  copy-pasted command resolves. The settings profiles that grant a pytest run allow
  `python3 -m pytest *` beside `python -m pytest *`, and a `python` test or build
  command found in the fingerprint derives both spellings, narrowed to its first
  argument rather than a broad `Bash(python *)` grant.
- **Packaging:** the published wheel no longer squats the top-level `tools/` import
  namespace; the sdist ships `SECURITY.md`, `CODE_OF_CONDUCT.md` and the bench baseline
  setup scripts and no longer carries internal development docs; the two maintainer-only
  release documents (`docs/RELEASE_CHECKLIST.md` and `docs/RELEASE_DECISIONS.md`) are
  classified internal and excluded from the sdist, the release archive and GitHub's
  "Download ZIP"; and the release archive is built from the git index, so an untracked
  file that is not gitignored can no longer ship. A root with no index to ask falls back
  to a working-tree walk and says so on stderr.
- **Walks and archives:** an embedded (nested) git repository left in the working tree,
  such as a leftover scratch target or a vendored git dependency, is excluded from the
  release zip, skipped by the drift, internal-leak and transient scanners, and omitted
  from fixture copies; an untracked secret in your own tree is still walked and
  detected. The bare `.git` *file* a worktree or submodule checkout leaves at its root
  is treated as transient rather than shipped. `safe_glob` no longer silently drops a
  trailing `prefix/**` pattern, and the recursive helpers now match `Path.glob("**/*")`
  exactly: a trailing `**/*` no longer yields the anchor directory itself, while a bare
  `**` or `prefix/**` still does.
- **`/recall`:** the two rankers' results now alternate, so the second ranker's winner
  is the second line you see rather than the third or fourth, and an exact score tie
  prefers the more focused document rather than the reverse-lexicographic path.
  `docs/STANDING_PRINCIPLES.md` is in the corpus, gated on file existence so your own
  principles document is indexed too. A `## ` line inside a fenced code block is no
  longer read as a section, through one fence-aware splitter shared with the banner. The
  retired promise that `/recall` stays silent on a no-match is corrected at every
  surface that carried it, because no threshold was found that suppresses off-topic
  English in a single-domain corpus without silencing real questions; and every
  description now states that up to four candidates are returned, alternating, rather
  than "the single most relevant piece".
- **`/recall`, what the banner advertises:** the session banner rendered a hand-written
  list of indexed source families that had missed `docs/STANDING_PRINCIPLES.md`; it is
  now derived from what the corpus actually yielded on that tree. When the retriever
  fails to import, the banner no longer states, from a process that never consulted the
  corpus, that a catalog is unindexed. A first sharp edge written above an undeleted
  placeholder sentinel, and ten ordinary edits to an untouched scaffold, are now
  classified correctly by comparing the section against the seed body rather than keying
  on one sentence surviving verbatim.
- **`/reflect`:** the hook side and the engine side now agree on what they scan (one
  shared pruned walk over `memory/` and every public folder-router `CLAUDE.md`), on what
  counts as placeholder residue (inline code stripped before matching, one shared
  pattern list and severity rule, append-only records exempt from the residue and
  density scans while still link-checked), and on what "recent" means (the last twenty
  log rows by time, with every historical timestamp spelling parsing). The broken-link
  scanner reports a genuinely broken link whose display text merely contains an angle
  bracket, and stops link-checking transient `cc/` prose.
- **`espalier recover` and the consistency check behind `/context-load`:** a
  source-release export (a "Download ZIP" or an extracted sdist) is no longer misjudged
  as a broken or degraded repository. Such an export ships the whole layout while
  intentionally pruning internal content, so a dev-tree consistency check cannot be
  satisfied; both now detect the export and stand those checks down, while a genuine dev
  tree or a fresh clone still gets the full check.
- **Shipped documents:** a batch of corrections so the docs describe the code. Every
  pointer in a document `init` deploys now resolves on an adopter tree or says beside
  itself that it will not, including invocations of scripts `init` never deploys.
  `docs/HOOKS.md` no longer lists `cc/LIVE_SURFACE.md` among files `init` does not
  write; the protected-zone enumerations in `docs/CONVENTIONS.md`, in the deny message
  and in the demo walkthrough (`docs/DEMO.md`) are pinned to the code that enforces
  them, and the deny no longer names `espalier/`, which is not a protected zone on an
  adopter tree; the three documents that quote the SessionStart banner quote what the
  deployed hook prints; the `hook-authoring` skill's wiring reference matches the
  canonical wiring and lists all ten governed events; `docs/FRESHNESS.md` stops claiming
  an unimplemented `weekly` policy branch; `docs/INSTALL-CI.md` states the exception
  where a repository already tracks its own `.claude/settings.json` and documents the
  workflow's real job-output gate; `docs/CHEAT-SHEET.md` stops telling a plain `init`
  adopter they lack two verbs that do ship; the Quickstart's clone command carries the
  real repository URL and its fusion path installs the CLI first; and six deployed
  command and skill bodies that described behaviour standing down off the Espalier
  source tree now say so. Two references in the deployed agent surface that pointed at
  documents which exist only in the harness's own repository are labelled at the point
  of reference.
- **Generated `CLAUDE.md` tables:** a literal `|` in a command, skill or agent
  description no longer spawns a phantom table column and corrupts every row after it,
  and a `description:` written as a YAML block scalar (`>-`, `|-`, `|2`) or wrapped in
  quotes renders its value instead of leaking the marker or the quotes. That renderer
  and the `cc/LIVE_SURFACE.md` renderer now share one set of scalar rules.
- **Shipped command and skill bodies:** every one dispatches a subagent by name,
  `subagent_type='<name>'`, rather than naming the tool. Claude Code renamed that tool,
  and the parameter spelling is the one that survives a rename. The three hygiene-gate
  messages use that single spelling too.
- **Denial messages:** the kill-switch denial names the setting that actually fired
  instead of always instructing removal of a `disableAllHooks` line, and the PowerShell
  dangerous-command denial is plain English with a `Don't:`/`Do:` pair and a
  narrow-the-target remedy instead of its raw regex source. A contract now walks every
  operator-facing denial template for the four required elements and forbids a raw regex
  from reaching reader-facing text.
- **Execution plan:** `mark` serializes its read-modify-write under a file lock, so two
  concurrent calls cannot lose an update; on Windows or a lock-less filesystem the lock
  degrades to a best-effort no-op rather than failing. `reset` names the demoted
  record's directory from the repository root (`demoted to cc/_cold/`), and `cc/_cold/`
  is gitignored so a reset no longer leaves an untracked file behind.
- **Governance gates and status commands fail safely on malformed input:** the release
  gate no longer greens a build with a corrupt config, `recover` and `/status` no longer
  crash or report a corrupt report as healthy, `doctor` flags a neutered governance hook
  as drift, and `espalier reflect` no longer tracebacks on a non-UTF-8 or
  byte-order-mark-prefixed report.

## [0.8.0a13] — 2026-05-28

Release-readiness hardening for the 0.8 alpha line. Version consistency is now
checked across every release surface (`pyproject.toml`, package metadata, and the
benchmark results table), so a version skew fails the release check instead of
shipping. The adopter CI workflow skips harness-self-host-only jobs cleanly on
repos that do not carry the engine source. Path and token matching in the surface
checks and the `.gitignore` suggestion moved to line-exact / token-boundary
membership, removing a class of false matches. See **[0.8.0b1]** for the
headline 0.8 feature set staged since 0.7.

## Pre-0.8 alpha — 2026-04-17 to 2026-05-28

Early alpha development (0.1.0 through 0.7.8). This span built out the core of
the harness: the repository fingerprinting engine; the mechanical hook governance
layer (the write / plan / config guards, the four-gate stop sequence, and the
session-continuity hooks); the cognitive-blueprint system that carries reasoning
across sessions; the stdlib-only scanner suite; and the packaging, release, and
adopter-CI tooling. Per-version detail for this pre-release history has been
condensed for the public launch. The per-release compare links at the foot of
this file resolve for any version whose tag has been published to the
repository.

---

[Unreleased]: https://github.com/Mike-Byrne-AI/espalier-harness/compare/v0.7.8...HEAD
[0.8.0b1]: https://github.com/Mike-Byrne-AI/espalier-harness/compare/v0.8.0a13...v0.8.0b1
[0.8.0a13]: https://github.com/Mike-Byrne-AI/espalier-harness/compare/v0.8.0a12...v0.8.0a13
[0.8.0a12]: https://github.com/Mike-Byrne-AI/espalier-harness/compare/v0.8.0a11...v0.8.0a12
[0.8.0a11]: https://github.com/Mike-Byrne-AI/espalier-harness/compare/v0.8.0a10...v0.8.0a11
[0.8.0a10]: https://github.com/Mike-Byrne-AI/espalier-harness/compare/v0.8.0a9...v0.8.0a10
[0.8.0a9]: https://github.com/Mike-Byrne-AI/espalier-harness/compare/v0.8.0a8...v0.8.0a9
[0.8.0a8]: https://github.com/Mike-Byrne-AI/espalier-harness/compare/v0.8.0a7...v0.8.0a8
[0.8.0a7]: https://github.com/Mike-Byrne-AI/espalier-harness/compare/v0.8.0a6...v0.8.0a7
[0.8.0a6]: https://github.com/Mike-Byrne-AI/espalier-harness/compare/v0.8.0a1...v0.8.0a6
[0.8.0a1]: https://github.com/Mike-Byrne-AI/espalier-harness/compare/v0.7.8...v0.8.0a1
[0.7.8]: https://github.com/Mike-Byrne-AI/espalier-harness/compare/v0.7.7...v0.7.8
[0.7.7]: https://github.com/Mike-Byrne-AI/espalier-harness/compare/v0.7.6...v0.7.7
[0.7.6]: https://github.com/Mike-Byrne-AI/espalier-harness/compare/v0.7.5...v0.7.6
[0.7.5]: https://github.com/Mike-Byrne-AI/espalier-harness/compare/v0.7.4...v0.7.5
[0.7.4]: https://github.com/Mike-Byrne-AI/espalier-harness/compare/v0.7.3...v0.7.4
[0.7.3]: https://github.com/Mike-Byrne-AI/espalier-harness/compare/v0.7.2...v0.7.3
[0.7.2]: https://github.com/Mike-Byrne-AI/espalier-harness/compare/v0.7.1.1...v0.7.2
[0.7.1.1]: https://github.com/Mike-Byrne-AI/espalier-harness/compare/v0.7.1...v0.7.1.1
[0.7.1]: https://github.com/Mike-Byrne-AI/espalier-harness/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/Mike-Byrne-AI/espalier-harness/compare/v0.7.0a2...v0.7.0
[0.7.0a2]: https://github.com/Mike-Byrne-AI/espalier-harness/compare/v0.7.0a1...v0.7.0a2
[0.7.0a1]: https://github.com/Mike-Byrne-AI/espalier-harness/compare/v0.6.6...v0.7.0a1
[0.6.6]: https://github.com/Mike-Byrne-AI/espalier-harness/compare/v0.6.5...v0.6.6
[0.6.5]: https://github.com/Mike-Byrne-AI/espalier-harness/compare/v0.6.4...v0.6.5
[0.6.4]: https://github.com/Mike-Byrne-AI/espalier-harness/compare/v0.6.3...v0.6.4
[0.6.3]: https://github.com/Mike-Byrne-AI/espalier-harness/compare/v0.6.2...v0.6.3
[0.6.2]: https://github.com/Mike-Byrne-AI/espalier-harness/compare/v0.6.1...v0.6.2
[0.6.1]: https://github.com/Mike-Byrne-AI/espalier-harness/releases/tag/v0.6.1
