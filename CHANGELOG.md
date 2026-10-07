# Changelog

All notable changes to Espalier-Harness are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
While pre-1.0, minor version bumps may include breaking changes.

---

## [Unreleased]

### Added

- **One table says what each stack is.** `tools/cc/_stack_table.py` holds, per
  stack, the source suffixes and their language, the manifests and lockfiles,
  the Node package managers (npm, pnpm, Yarn, Bun) with the argv that runs a
  script under each, the dependency and build-output directories, the lint
  `/preflight` falls back to, and the rules rendered only for that stack. It
  imports nothing but the standard library. The hooks import it; the engine
  imports a byte copy, `espalier/_stack_table.py`, which `python3
  scripts/sync_vendor_cc.py` writes beside the vendored tree (a tenth mirror
  row, `stack-table`, with its own edit-time advisory). `init` deploys the
  table with the other `tools/cc/` modules. The settings renderer reads its
  script runners and its Python-only rules from the table, so a package
  manager added there is narrowed to its script names with no second edit.

  `tests/test_stack_table.py` holds the hand lists to it. Every collection
  literal in `espalier/` and `tools/cc/` that spells a dependency directory,
  two or more source suffixes, two or more manifests, or a lockfile must
  derive from the table or carry a `# stack-table: ok purpose-scoped --
  <reason>` comment. The lists that still spell one by hand are a dated
  baseline that may only shrink: 25 when the table landed, 18 after the
  source-and-manifests lane (every one left is a dependency-directory list). A fixed seed of names is held to the
  table's projections, so a name deleted from the table reds even after no
  hand list spells it. `/preflight`'s fallback lint ladder stays bash, and is
  held to the table both ways: every stack with a fallback lint has a branch
  guarded by one of its manifests, and every guarded branch is a table
  stack's.

- **The suite can build a Node, Go or Rust adopter tree, not only a Python
  one.** `tests/_stack_trees.py` is one stdlib-only table holding every
  synthetic project tree the suite writes.
  - The six portable stack fixtures in `tests/conftest.py` now write rows of
    that table. The rows were proven identical to the old fixture bodies
    before the switch.
  - The three fixtures nothing used are gone.
  - `build_adopter_tree` gains `stack=` (a Python, Node, Node-under-pnpm, Go
    or Rust project), `tree=` (just the files, a committed git repository,
    or the full `init` plus `install-ci`) and `branch=`.
  - The selfcheck mirror carries a byte copy of the table, so `espalier
    selfcheck` builds its fixtures from the same rows.
  - Trees are written byte for byte, so they are identical on every host.
    Before, a fixture written on Windows got CRLF line endings.

  `tests/test_stack_trees.py` installs every adopter stack and checks the
  fingerprint reads each one as its language. The Node trees do not yet:
  their `.mjs` and `.astro` sources read as no language at all. That is
  recorded as an expected failure that names its ledger row, so it reports
  loudly once the row's fix lands.

- **The suite now records which adopter shapes it actually runs on.**
  `tests/_axis_registry.py` names five axes an adopter can differ along: the
  stack, which interpreter names answer, one event versus a session that
  carries state, a path holding a space, and a dirty or CRLF tree. Each
  `(axis, value)` cell either names the test that proves it or declares its
  gap with a reason. `tests/test_axis_registry.py` checks each proving test.
  It must be parametrised with an argument named after the axis, at the
  cell's value, carry no skip or expected-failure mark, and pass when it runs.
  So a cell cannot be proven by a test that never varies along it. The stack
  and host cells are derived from the stack table and the stubbed-PATH host
  shapes, and the proven count is held at a dated floor. The registry lands
  with every cell a gap, and running `python tests/_axis_registry.py` prints
  the table, with each blind axis named. Measured before it landed: deleting
  the Node extensions from the hooks' source set changed 0 of 329 verdicts in
  the files that read it, while deleting `.py` changed 8.

- **The banner names another live Claude Code session in the same tree, and
  a roadmap pack maps the same-machine half of the anti-clobber system.** The
  two-machine half is complete by shape (the mail channel, claims with row
  ids, the record merge, the conflict-marker gate); between two sessions on
  one machine the claims key on the machine name and every current-X file
  (`cc/execution_plan.json`, `cc/blueprints/latest.json`,
  `cc/_working_summary.md`, the per-session flags) is a singleton with no
  session key, and a session that enters a worktree mid-session writes its
  state into the main tree, because its hooks keep `CLAUDE_PROJECT_DIR` there.
  Wave A, landed here: `session_start.py` writes one marker per session under
  `.espalier-state/sessions/<session_id>.json` (the payload's id, sanitised
  before it names a file), `task_router.py` touches it on every prompt, and
  the banner carries a `Sessions:` line naming each other marker touched
  within four hours -- id prefix, when it started, when it last prompted, what
  the two share and the sharp edge to read -- omitted when none; markers
  untouched for seven days are swept at start; the sibling's recorded `cwd`
  is shown when it differs from this root. A `clear` retires the sibling
  markers recording this hook's parent pid (a clear mints a new session id,
  measured; on macOS the hook's parent is the Claude Code process itself, so
  that pid names the window and the handoff-then-clear loop is not told about
  itself; a per-spawn shell matches nothing and retires nothing). The marker
  lives in a directory, not a flag, so a fresh start's flag sweep never
  reaches a sibling's (`_hook_utils.SESSIONS_DIR` and the helpers beside it
  are the single owner for the three hooks; the state-dir roster in
  `tests/test_state_file_flag_parity.py` admits it). Reporter only; the
  review batch (one code-reviewer, one failure-mode reviewer on a snapshot
  clone) added the roster entry, the clear retire, the cwd, the audible
  marker-write failure, a heartbeat that beats before the prompt's shape is
  checked, and the launched-worktree wording. Waves B to D (a name per
  worktree through `WorktreeCreate`/`WorktreeRemove`, the singletons keyed by
  session, release at `SessionEnd`) are the pack's; the earlier drafted
  multiagent-worktree pack is superseded and the worktree-governance inventory
  row routes to wave B. Two doc sentences claiming separate worktrees
  never collide now carry the entered-mid-session caveat.
- **A claim on the mail channel names the ledger rows a lane touches or
  mints, the ledger verbs read it before they write, and a shipped lane
  releases its own claims.** The other box had been writing "DEF-1131 is
  taken here; file from DEF-1132" into claim prose; `ids` is now a field of
  the claim's `re` block (`--id`, repeatable; additive, so a reader from
  before it ignores the key). `tools/cc/ledger_row.py`'s `file`, `strike` and
  `repin` read the other machines' live claims from the local refs before
  taking the ledger lock: a claim naming the row's id refuses by name, with
  the holder, the lane, the claim's time and `--override` as the way past
  (one id minted on two machines, or one row changed on both sides, is what
  the record merge refuses at the pull request, so the write stops where the
  holder can be asked); a claim naming only the row's class is a note, since
  two rows in one class merge cleanly, except for the `class` verb, which
  mints a section and refuses on one; a row with more than one id is read by
  every id on its cell. The read is of the local refs, so a claim made on the
  other box after the session's fetch is invisible until the next one, and
  the record merge stays the backstop for that window. The channel module is
  loaded lazily by path inside the same fail-open as the reads, so a copied
  subset -- the channel present without its own sibling included -- writes
  as before with a note. The ship driver's `open` and `handoff` verbs release
  this machine's live claims on the lane once the push lands, a refusal after
  the push included, and say when live claims remain under another lane
  name -- a claim's lifetime is the lane's time on the machine, where before
  `/handoff` sent no release and an unreleased claim warned forever.
  A new sharp-edges entry records that the worktrees of one clone share its
  `.git/config` and so one machine name, which hides a sibling's claims, with
  git's per-worktree config as the hatch.
- **A merge-conflict marker left in a record file is caught at the write and
  refused at the merge.** Until now neither the merge gate, the scanners nor
  the post-write hook read a record file for a marker line: a hand merge left
  the memory file half-merged, the commit landed the hunk, every gate stayed
  green, and the next session's banner read a memory row that was three
  marker lines. `tools/cc/ci_guard.py` now carries a fourth unconditional
  check, `check_record_file_markers`, over the memory file, the forward ledger
  and its probe roster (read whole, so a marker that survived an earlier
  merge is caught on the next run); git's own rule, a line opening with the
  seven-character head and a space or nothing; the red names the file and
  the line, and the approval marker does not waive it. The post-write hook
  reads the same roster back after a Write, Edit, NotebookEdit or MCP write
  and names the lines as `additionalContext` on the tool result -- that
  channel, because a hook that exits 0 has its stderr dropped from the
  transcript by protocol -- outside the self-host gate, since an adopter
  whose `init` seeded a tracked ledger is the named user, and it reads the
  bytes the way the gate does (a byte-order mark of any width). Two more
  sites from the failure-mode review: the SessionStart banner's memory
  digest, which a hand merge through Bash reaches with no write hook in
  between, skips the marker lines and names them instead of printing them
  as the memory's first lines; and the ship driver's preflight, open and
  handoff verbs refuse to push a lane whose record files carry one, since
  the gate would red every required cell. The rule is column zero, so a line
  that only quotes a marker is read as one too, and every red says to indent
  the quote by one space. The hook side's rule and roster have one owner
  (`_hook_utils`); the four hand copies of the roster (the resolver's is the
  home) and the three carriers of the heads are pinned equal, the two
  readers driven on one vector.
- **A required cell that a lost runner ended is re-run once, by name, and
  never counted green.** On 2026-10-05 two required cells of one pull
  request ended `failure` with no step failed (a step `cancelled`, "The
  operation was canceled.") and auto-merge waited on them until a session
  re-ran them by hand. `tools/cc/ship.py` gains `rerun` (`--dry-run` names
  what it would do): it re-runs, once, the required cells whose runner ended
  them -- the two shapes measured over sixty pull-request runs of the test
  workflow (a job no hosted runner picked up; a step cancelled mid-run with
  none failed), a positive list, so a failed step, a run a newer one
  superseded, a hand cancellation and a job that outran its timeout stay
  decided. It re-runs nothing, and says what to do instead, while anything
  else holds the merge: a decided required red, a run still going or already
  re-run (GitHub's attempt counter is the bound, so "once" holds across
  sessions and machines), a lane behind or in conflict with its base, or
  another red in the same run, which `gh run rerun --failed` would retry too.
  The match is on GitHub's wording, so a cell with the right outline and notes
  it does not know is printed as `required red, cause not read:` with the
  command that shows its log -- where a rewording would show. `status` stays
  read-only, no longer reports a cancelled required cell as "no required
  check is red", and names a lost cell apart (`required, runner lost:`) with
  the command or the reason it cannot take one. The SessionStart banner
  counts a cancelled required cell red too, and its held tail now sends a
  required red to `ship.py status` rather than straight to "fix, push,
  re-bind" (a re-bind never re-runs a lost cell). Not automatic yet: a
  session or the operator runs the verb.
- **One box's Claude can leave the other a message, and claim an area, with
  no shared live session.** The mail channel (`tools/cc/mail.py`, deployed):
  one append-only ref per machine on origin (`refs/heads/mail/<machine>`),
  never merged; one `mail.jsonl` per ref, one JSON object per line; five
  message types (`claim`, `release`, `note`, `request`, `ack`), each naming
  the lane, classes and paths it is about; the live claims are the fold over
  claim and release. A send builds its commit under a scratch index from the
  message alone, moves the ref by compare-and-swap and pushes without force,
  so a second checkout writing under the same name is refused, never
  overwritten; a message whose text or paths read to the guard as a
  secret-bearing path is refused, because the channel lives on a public
  origin. `git config espalier.machine <name>` names the box and turns the
  channel on -- per clone, never tracked, since a key in `espalier.toml` would
  hand every clone one name. The SessionStart banner carries a `Mail:` line
  of the other machine's unread headlines (one bounded fetch under the
  pull-request block's budget; a nameless clone that already holds another
  machine's ref is told how to opt in), the compaction re-orient an unread
  count, `/inbox` the bodies,
  the live claims and the send, and `/implement-task`'s plan creation warns
  when a step's `files:` or `classes:` meet another machine's live claim.
  Ledger row `DEF-1129` is the retirement clock: two weeks with no
  cross-platform request fulfilled retires the channel.
- **A merge can no longer carry a stale probes count into its commit**
  (`DEF-1128`, closed): the record merge settles the roster's `_count`
  against its list after ANY merge, clean or conflicted, under the ledger
  lock, re-derives the ledger's regions against it and folds a moved count
  into the merge commit; a settle that cannot run undoes the merge to the
  pre-merge head. Driven by the resolver's own first live run, where main's
  roster carried a count a hand merge had left behind and the merge commit
  declared it. And a ledger probe now answers about the tree, never about
  the terminal: `check_ledger_probes.py` strips `CLAUDECODE` from every
  probe's environment, so a probe that runs `clean-generated --execute` no
  longer reads UNRESOLVED from inside a Claude Code session (`DEF-1057`'s
  did, since the live-session guard landed).
- **Two machines' lanes no longer wait on a hand to merge.** Each `/handoff`
  prepends a row under the same Session Log header and each ledger verb files
  into the same first slot and rewrites the same counts, so two lanes landed
  between syncs conflicted by construction on `ESPALIER_MEMORY.md`, the
  forward ledger and its probes file -- and GitHub's own merge honours no merge
  driver, so the second lane read `CONFLICTING` until someone resolved it by
  hand (three times on 2026-10-05 alone). The ship driver now merges the base
  in locally and resolves those files by shape (`tools/cc/record_merge.py`,
  deployed beside it): the memory file keeps every row either side added,
  drops every row either side evicted and is pruned back to its cap with the
  merged-in rows kept; the ledger keeps both sides' member and index rows and
  re-derives its counts; the probes roster unions by id. `catch-up` takes that
  path when GitHub reads the lane `CONFLICTING` (waiting out `UNKNOWN`), and
  `open` and the handoff's push take it before pushing, so a lane is born
  mergeable and the merge rides the one push. Anything the resolver cannot
  classify -- a prose edit on both sides, a row changed on both sides, one id
  filed on two machines, a path outside those three files -- aborts the merge
  and is refused by name. `preflight` prints the verdict, the banner's conflict
  row names the verb, and this repository's changelog takes a `merge=union`
  attribute for that same local merge. Proven on a bare origin with two clones
  and by replaying the day's live collision.
- **You can decline one of the harness's required `.gitignore` entries.**
  List it under `gitignore_declined` in `espalier.toml` (most often
  `/task-packs/*` on a repo that versions its own packs): `init` and
  `upgrade` stop appending it and `doctor` lists it as information instead
  of a warning. A value that is not a required entry changes nothing, and
  `doctor` warns about it. For a missing entry that hides whole folders,
  `doctor` now says files there stop staging instead of calling a re-init
  safe.

- **A setting the user wrote, a gate the user armed, and a fault inside a
  guard each say so where the user looks.** `espalier.toml`'s
  `protected_paths` ("never touch", every channel, at a path boundary) and
  `generated_paths` ("regenerate; do not hand-edit", refused on Write /
  Edit / NotebookEdit only) are now read by `write_guard` on every call, and
  the deny names the key and the zone instead of the maintenance-mode
  relaunch (bench row BC-062). An unknown top-level key in `espalier.toml`
  loads with a warning naming the file, the key and the nearest known one,
  and `espalier doctor` reports it. Every deciding fail-open handler in the
  hooks speaks (`say_once`: one stderr line and one `*_failed_open_*` audit
  record per session, so `/status --log` counts it) or declares its kind,
  gated by a derived census; a payload a blocking hook could not read allows
  and says so once. Every gate spawn routes through one chokepoint that
  resolves the program first (so the stop-time `npm test` override finds
  `npm.cmd` on Windows) and returns a typed failure instead of raising; the
  SessionStart banner names, in its Warnings block, an override whose first
  token will not start.
- **`/ship`** pushes the lane you just committed as a pull request with
  auto-merge armed and the approval marker bound to its final head; a
  `--release vX.Y.Z` flag tags the merge commit and creates the release. The
  SessionStart banner gains `Open PRs:` and `Merged:` lines naming your pull
  requests, their check tally, and the pull that catches your base branch up.
- **A goal/progress snapshot by default.** `espalier init` (and `upgrade
  --execute`) now create `cc/GOAL.md` when it is absent: a short file every
  session start shows near the top and `/handoff` keeps current, with the
  goal-proper last so it survives when the banner trims. It is added to the
  `.gitignore` block, never overwritten once it exists, and `goal_snapshot =
  false` in `espalier.toml` turns the seeding off (delete the file too).
- **A forward ledger in every repository.** `espalier init` (and `upgrade
  --execute`) now seed `task-packs/FORWARD_LEDGER.md` -- the tracker the review
  workflows already read to avoid re-reporting known work -- and file its first
  rows: seven onboarding steps (set the goal, confirm the hooks and the tests,
  check the repository category, decide which folders need a plan, replace the
  conventions stubs), each re-checked by a probe or marked as a judgement. The
  verbs that file, close and re-check rows ship in `tools/cc/` (`ledger_row.py`,
  `check_ledger_probes.py`, `generate_ledger_regions.py`), take a lock so two
  never run at once, and `/preflight` runs the probe check. The ledger is
  committed: the `.gitignore` block now ignores the contents of `task-packs/`
  (your pack drafts) and keeps the ledger, its probes file and the folder's
  `CLAUDE.md`; a re-init rewrites the older `/task-packs/` line inside the
  harness block, and names -- without editing -- a rule of your own that would
  keep the ledger ignored.

- **The SessionStart `Merged:` line names a check that went red after the
  merge.** A check that is not required finishes after auto-merge has landed
  the lane and reports to nobody: the Windows leg went red 28 minutes after one
  pull request merged, and the banner said nothing. The line now names each
  recently merged pull request whose latest run of a check is red (`red after
  merge: portability (windows-latest)`), owning each check by the newest merge
  whose run of it reached a verdict, so a run of docs-only merges cannot hide a
  red code merge, a later green run of the same check clears it, and a leg still
  pending on the newer merge supersedes nothing; a cancelled or stale latest run
  reads `no verdict:`. `/ship` step 0 makes the same read over the last twenty
  merges before a new lane is armed. No new `gh` call: the rollup was already
  fetched.
- **A first-week adopter meets fewer harness surprises.** `init`'s CLAUDE.md
  nudge reads the document Claude Code composes, following `@` imports one
  level (inline tokens, home-directory paths, never a fenced example), so a
  thin adapter file draws no NOTE for sections one import away. When a
  Prettier, markdownlint, mdformat or dprint configuration is at the root,
  `init` and `upgrade --execute` print an ignore snippet derived from what
  they wrote, and `espalier ignore-snippet --format prettier` reprints it;
  the adopter's ignore file is never written. `espalier doctor` carries a
  Gate 1 row saying what the stop-time test gate would run, as a warning when
  `ESPALIER_STOP_GATE=full` is set against a gate that runs none of your
  suite; the init summary names the detected test command and both
  variables; `ESPALIER_STOP_GATE_TEST_CMD` is in every default surface that
  names the gate.


### Changed

- **The source suffixes, manifests and lockfiles the harness knows are read
  from the stack table on both sides of the no-import boundary.** The hooks'
  source set (`_hook_utils.SOURCE_LANGUAGE_EXTENSIONS`) and the fingerprint's
  language map (`analyze.SUFFIX_TO_LANGUAGE`) are now one projection of
  `tools/cc/_stack_table.py`, so `.h`, `.scala` and `.swift` files read as
  languages (a Swift repository fingerprinted as no language before, while
  the hooks gated it as source). The package systems are the table's rows
  whose manifests sit at the root, in row order: a `setup.py`, `setup.cfg`
  or `Pipfile` tree lists `python`, a `Gemfile` tree lists `ruby`, and a tree
  holding both `go.mod` and `Cargo.toml` lists `go` first, and its test
  commands `go test ./...` before `cargo test` (the test-command provider and
  the foreign-manifest suppressor derive from the same rows). The
  package-root markers stay the six project manifests they were, held as a
  filter on the table (a per-manifest flag the table does not carry; widening
  them to a vendored `setup.py` would flip `monorepo`, so that is a candidate
  row). Every
  manifest and lockfile in the table at the repository root needs an
  execution plan (`go.mod`, `go.sum`, `Gemfile`, `bun.lockb`, `Pipfile`,
  `pom.xml` and `build.gradle` were exempt). `/scope-check` walks the
  adopter's own source: on a Node tree it found a symbol's `.mjs` definition
  and `.ts` use nowhere. The scan offer and the two "scanners are
  Python-specific" notes read the table's `ast_scannable` flag. The hook
  layer reads the table behind a guarded import: a deployed copy that is
  missing, hand-patched into a syntax error or older than the hooks leaves
  every gate running on a pinned copy of the table, held equal to it by
  test, and `plan_guard` and `reflect_trigger` say so once a session. The
  Go and Rust adopter trees are driven by the Node-defaults module (their
  stack cells are proven; the floor is six).

- `/handoff` pushes only where `espalier.toml` sets `handoff_push = true`. A push
  is outward-facing, and nothing but the agent's own care told a new user that
  `/handoff` pushed, so the default is now off: the handoff commits its memory
  row and the driver's new `handoff` verb (`tools/cc/ship.py handoff`) says how
  to push the lane (`/ship`) and how to opt in. `init`'s summary names the
  setting. With the key on, the handoff's push is the lane's one push, and
  `ship.py open` refuses a lane whose commits never touch `ESPALIER_MEMORY.md`
  unless given `--early "<reason>"`, since the handoff's row would then become
  a second push; the date-keyed notice this replaces missed a second lane on
  the same day.

- The per-pull-request check cycle is shorter in three ways. The heavy end-to-end
  stages (`tests/conftest.py::_HEAVY_E2E_TESTS`) left the per-pull-request tier:
  every pytest line of `scripts/proof_tier.py` deselects them, `--heavy` puts them
  back, and they keep two homes, the floor-version `clean-checkout` cell and the
  fresh-clone gate's first leg (the stage-one smoke alone measured 848 s of a
  992 s parallel leg in a cell). The tier's serial leg runs beside the parallel
  one in five `test-serial (3.x)` cells (`--leg`), instead of after it inside each
  `test` cell (8 to 14 minutes of every cell). The `clean-checkout` job moved to
  its own workflow on the floor interpreter, so a flaked required cell can be
  re-run without waiting on it. Branch protection gains the five serial cells by
  an operator step after this lands; the ledger carries the command.

- **Ship once, from anywhere.** The `/ship` flow is now a deployed driver,
  `tools/cc/ship.py`, one verb per step (`preflight`, `lane`, `open`, `rebind`,
  `catch-up`, `status`, `release`), the same on macOS, Linux and Windows: it
  refuses by name the state each step must not act on (a dirty tree, an empty
  range, a lane whose remote copy has commits this HEAD lacks, a pull request
  that is not at HEAD, a tag that is not the tree's version or already
  exists), creates the pull request **with the approval marker already in the
  title** when the diff needs one (one event, one check run, no title edit for
  a race to lose), arms auto-merge and reads the arming back, and strips every
  stale binding when it re-binds. The core flow now reads `/commit`,
  `/handoff`, `/ship`: a session pushes each lane once, at its end, with the
  handoff's row on the same push -- `/handoff` hands to the driver as its last
  step, and `/commit` names the cost of shipping early. The harness-guard
  `verify` job reads the pull request title **as it is at check time** (a
  `gh` read with the job's `pull-requests: read` token, the event payload's
  title as its fallback, said aloud), because a push and a title edit are two
  events on one head and the concurrency group keeps whichever run GitHub
  created second, an order GitHub does not promise; a run born from the push
  had judged a title that was already re-bound and left an armed auto-merge
  blocked with the title correct. The SessionStart banner's `Open PRs:` line
  now says what holds a merge GitHub reports as blocked -- the required red by
  name, from one more bounded `gh pr checks --required` read on a row with a
  red, or the running count -- instead of "it merges unless a red check is
  required". The release speed bump fires on the driver's `release` verb as it
  does on a tag push and `gh release create`.
- **The settings backup ladder moved.** A wire's pre-write copy of
  `.claude/settings.json` lands under `.espalier/settings-backups/` as
  `settings.json.<n>.json` (gitignored, a non-archive name), never beside the
  tracked file; legacy `settings.json.bak` rungs stay recognised for the
  dedup, listed by the uninstall, and never pruned. `/smoke` checks 1, 2 and
  4 read the harness's own inventory (`cc/COMMANDS.md`) by membership and
  print `[SKIP]` where an adopter-owned CLAUDE.md carries no table, instead
  of a vacuous pass and a permanent count mismatch. The working summary's
  transcript pointer is a session reference (stem plus the resolving
  command), never an absolute home path. A pytest tree holding one of the
  harness default test file names resolves `ok_harness_defaults` with a note
  that names the override, so a partial Gate 1 is never silent.


### Removed

- **`/accomplish` is retired.** It was the compatibility alias for
  `/implement-task --multi`; a tree that deployed it hears about the retired
  file from `espalier init` and `espalier upgrade`, which name it and never
  delete it. `/implement-task --multi` is the command.

### Fixed

- **A cleanup of scratch below a temp root no longer draws the
  recursive-delete nudge.** The nudge recognised no temp root, so a
  recursive delete in the system temp directory, either Windows temp
  spelling or `mktemp` scratch drew it on both tools; a read-only miner over
  a Windows host's transcripts counted 115 such nudges among 180 guard
  refusals, 113 naming temp or scratch (`DEF-1037`). One helper beside the
  ephemeral roster now passes a literal path strictly below a temp root --
  the directory `TEMP`, `TMP` or `TMPDIR` names, a drive-root tmp or temp,
  a POSIX temp root -- read from the directory the command runs in, through
  its literal bindings and, on Bash, a `mktemp` binding that makes its
  directory there, on the Bash tool and for PowerShell's remove forced or
  not and its sweeps. A git checkout or worktree below a temp root, this
  project's checkout, a home that lies below one, the temp root itself and
  a temp directory nested below another with its parents, a variable, a
  wildcard and a parent step keep the nudge or the wall. The wall texts and
  the hooks reference say which paths pass.
- **A direct child of a repo one level under a drive root is the nudge's
  on PowerShell, and the deny texts say what the unforced remove walls.**
  The PowerShell judge walled every path two or fewer levels below a drive
  root before it asked whether the path sat inside the repo or the home
  directory, so the unforced remove of a build directory in a repo at a
  drive root's child met the wall maintenance mode cannot bypass while its
  deny text said a path inside the repo is not refused (`DEF-1041`). The
  drive path is now compared as typed against the repo and the home first;
  a match lifts only that rule, so the repo itself and a parent step out of
  it stay walled. The forced remove's drop -Force remedy promised one nudge
  for every path but a drive root, the home and the repo, which the
  unforced tier contradicts on every other shallow drive path (`DEF-1042`):
  the remedy and both PowerShell wall texts now carry one phrase for what
  that tier walls, with drive examples. The Bash tool still reads a drive
  path one level deeper; that difference is declared and pinned.
- **The glob relief reaches the forced PowerShell remove.** A bare leading
  wildcard in a plain command is read as the directory it expands in on the
  Bash tool and for PowerShell's unforced remove and sweeps, but the forced
  remove -- the spelling the hooks reference names first -- walled it
  wherever it ran, so the same clean of every build directory was one nudge
  on Bash and the wall forced on PowerShell (`DEF-859`). The forced reader
  now takes the relief from the same bases, so it draws the nudge; the bare
  wildcard from the checkout, a wildcard in a command that is not plain and
  a parent step stay the wall.
- **A command the guard cannot judge in time is refused, not let through.**
  Claude Code cancels `write_guard` at its wired 5 s timeout, and a cancelled
  PreToolUse command hook does not block, so a judgment that ran past it --
  a long generated delete list, 10.6 s at 2,000 relative paths on the Bash
  tool and 6.0 s at 1,000 on the PowerShell tool, measured -- skipped the
  wall, the nudge, the zone check and the kill-switch gate for that call
  with no notice beyond the debug log (`DEF-1160`; the slow `set` scan of
  `DEF-1071` is the same mechanism).
  - The guard now judges every call in a worker thread under a 3.5 s budget
    counted from the hook's first line, on every tool and under maintenance
    mode too. When the budget runs out first it denies the call as it denies
    any other, one deny decision whose reason asks for the command to be
    split into shorter ones, and writes one `pretooluse_blocked_time_budget`
    record that `/status --log` counts; driven end to end, the refusal lands
    about 3.6 s after the spawn.
  - One claim decides the verdict, so a judgment that ends at the instant the
    budget does yields one decision, and nothing the refused judgment prints
    reaches stdout. The appends the guard reaches write their bytes under one
    state-write lock that the refusal takes before it exits, so a refusal
    never leaves a torn line in the audit, discard-snapshot or telemetry log.
  - An ordinary call is unchanged: the same output, and its latency moved by
    no more than the run-to-run spread (within 13 ms either way across five
    ordinary payloads, interleaved, on the Windows self-host box).
- **An adopter's own ruff no longer reds on the files the harness deployed.**
  `/preflight`'s inferred `ruff check .` now carries `--extend-exclude
  tools/cc`, the exclude the body's PATH fallback already spelled (the
  fingerprint's own string is unchanged, and a declared `[extra_actions]
  lint` runs as written), and `init` and `upgrade --execute` print the one
  `[tool.ruff]` line, `extend-exclude = ["tools/cc"]`, whenever ruff is
  declared -- printed, never written, like the Markdown-formatter snippet,
  and reprinted by `espalier ignore-snippet --format ruff`. Measured
  2026-10-06 on a fresh init: 412 findings in the vendored files under ruff's
  defaults, 1,683 under a common selection, none in the adopter's own files.
  A nested ruff configuration under `tools/cc/` was measured and not shipped: it shields a
  discovery-mode run only, not `--config` or `ruff format`, and it writes a
  cache directory inside the protected tree (DEF-1154, closing §C55).
- **The Windows prefix spellings of a protected file read as that file.**
  The extended-length and device forms (`\\?\C:\`, `\\.\C:\`) and the
  loopback administrative shares (`\\localhost\C$\`, `\\127.0.0.1\C$\`),
  which long-path presentation and a mapped share put on an ordinary path,
  fold to the drive path at the drive-spelling chokepoint
  (`_hook_utils._windows_prefixes_to_drive`, inside `_msys_drive_to_windows`),
  so every channel's zone check, the root side and the recursive-delete
  tier read the drive form with no edit of their own. Walk 4 had measured
  nine of eleven such spellings passing every hook on the Windows host,
  because `ntpath.realpath` keeps a prefix its input carried; the residual is
  a share spelled by anything but the two loopback names (DEF-935).
- **A hidden name is never a member of a `.claude` kind, at every enumerator.**
  `espalier._safe_walk.visible` (with `is_hidden_name`) is the one predicate:
  the engine's `discover_claude_kind`, `init`'s deploy enumerator, the packaged
  asset walker and five more engine globs, the deployed `session_resume` counts
  (their own two-line form, since `tools/cc` imports no engine), the sync and
  release scripts and 57 test-tree sites route through it, and a derived pin in
  `tests/test_package_resource_parity.py` finds every listing over a kind
  directory by scanning the tree rather than from a list.
  - Driven 2026-10-06 on a clone carrying one `._<body>.md` AppleDouble sidecar
    and one `.DS_Store` under the agents and commands directories of the root
    and both mirrors: 16 rows across five modules reported a wrong count or a
    parity gap and never named the sidecar, the parity rows' own remedy would
    have copied it into both mirrors, and the engine's own discoverer counted
    it, so `doctor`'s inventory and the uninstall would have on a macOS
    adopter's tree (DEF-479, DEF-489, §C28).
- **The pin-isolation control no longer watches the harness's own session
  state.** `.espalier-state/` joined the churn roster in `tests/test_verify_pins.py`
  on an observation: two manifest snapshots one tool call apart differed on
  exactly `last_tool` and `tool_call_count`, and since the per-session markers
  every prompt of every live session moves the tree too (DEF-663).
- **The git oracle returns a non-ASCII tracked name as itself.** Both helpers
  in `tests/_git_oracle.py` and the worktree-deleted read beside them pass `-z`
  and split on NUL, so `ü.md` no longer comes back as git's C-quoted
  `"\303\274.md"` under the default `core.quotePath` (DEF-683).
- **The record-boundary row skips, by name, on a handoff-started archive.**
  The verdict is a pure function over record states with the witness pinned
  (the archive, `Harness Guard`, the 2026-08-12 row): a present gitignored
  archive whose oldest row is younger than the witness cannot hold it and reads
  as absent, with a skip naming the archive and both dates, while an archive
  reaching past the witness and silent stays the red the row exists for
  (DEF-969).
- **The shared fixture repo never runs a background git.** `initialized_repo_root`
  sets `gc.auto 0`, `gc.autoDetach false` and `maintenance.auto false` right
  after `git init`, after #123's `test (3.14)` cell errored copying a
  `tmp_pack_*` a git process wrote and removed under `self_host_tree_copy`'s
  listing; a traced build shows one maintenance child before and none after
  (DEF-1168).
- **Two more launch forms of a recursive delete meet the plain form's
  tiers.** On the PowerShell tool the native remove binary reached by its
  file name or a path, and on both tools cmd.exe's own recursive directory
  and file deletes in a program a cmd launch runs, met no wall and no nudge
  while the plain recursive remove of the same target was walled
  (`DEF-1123`, `DEF-1151`).
  - Both are read through the shared remove verb and one cmd reader: the
    wall on a catastrophic target (cmd's home-directory variable read as the
    home), nothing on a roster build directory, one nudge on any other.
  - On both tools the zone check reads every delete cmd runs, recursive or
    not, by cmd's own grammar: a protected directory removed through cmd --
    behind cmd's existence test too -- meets the nudge and then the zone
    wall on the re-issue, the plain form's order.
  - cmd's switch run glued before its program switch is read as the
    separate switches cmd reads, for the delete reader and the
    harness-variable check that share the walk.
  - A property crosses every verb form the readers declare -- the verb
    names from the guard's own rosters, the path shapes a hand list read
    back through the reader -- with the hard-tier texts' target claims, so
    a form or a target added to either is asked of the other.
  - Declared limits: a `cd` inside cmd's own program is not followed, a
    narrowing `del /s` pattern is the zone check's alone, and a bare path
    longer than 256 characters before the native binary's name is read by
    no reader.
- **Where the PowerShell wall steps aside on a recursive remove, the nudge
  asks** (`DEF-1124`).
  - A property over a generated population -- every launch form, its switch
    spellings forced and not, targets on and off the ephemeral roster, three
    quote styles and three statement shapes -- pins that a step-aside is a
    nudge unless every target is on the roster.
  - The roster is read through one exemption helper that the wall's
    carve-out, both nudges and the property share.
  - The existence-guarded cleanup idiom on a roster directory no longer
    draws a nudge the plain remove does not (the forced reader read the
    block's closing brace as a target), and a comma-built array with a blank
    beside its comma is judged element by element.
- **A pnpm, Yarn or Bun project is no longer told to run npm.** The engine
  had no reader for a lockfile or for `package.json`'s `packageManager`, so
  every Node tree inferred `npm test`, `npm run lint` and `npm run build`. Now
  `packageManager` (`"pnpm@9.12.0"`, read by name) decides first, then the one
  lockfile at the root (`package-lock.json` or `npm-shrinkwrap.json`,
  `pnpm-lock.yaml`, `yarn.lock`, `bun.lock` or `bun.lockb`), then npm.
  - The inferred commands follow it: `pnpm test` and `pnpm run build`, `yarn
    test`, and `bun run test` (not `bun test`, which runs Bun's own test
    runner instead of your script). `/preflight` runs them, and the
    workflow profile's narrowed rules name them.
  - The fingerprint records the answer and what said so
    (`package_manager`). Drift compares the manager's name only, so the
    lockfile the first `npm install` writes is not drift.
  - Lockfiles of two different managers are not guessed between: the
    commands stay npm and `espalier doctor` warns, naming the files, the
    lockfile to delete and the `packageManager` field that settles it
    (`[extra_actions]` sets the commands `/preflight` runs, and the doctor
    step says it does not clear the warning).
  - A lockfile one directory down belongs to that package, not to the
    repository, and is not read.

- **The suite's package builds no longer run in the live tree.** `build_wheel`
  and the new `build_sdist` in `espalier/artifact_parity.py` copy the working
  tree into a per-call temp root (the git store, `build/`, `dist/`, every
  `*.egg-info`, the caches and the session state left out) and build there;
  the wheel and sdist payload fixtures build through them.
  - Under xdist, another worker's tree walk could see the sdist's staged
    release tree or a cleared `build/` and red a required cell on a pull
    request whose diff never touched the file named (`DEF-1138`, seen on
    #116's `test (3.14)` cell).
  - Each payload fixture reads the root's packaging litter (name and mtime)
    before and after its build and reds if the build wrote the live tree.
  - The skip set is pinned to `MANIFEST.in` and `.gitignore`, so the copy can
    only leave out what no artifact ships; no tracked path carries a skip name.
  - The copy also leaves out `cc/blueprints/`, `bench/results/` and
    `bench/end_to_end/runs/` whole: a copy reads the live tree, and an entry a
    live session rotates mid-copy would raise out of the fixture (the review
    round, driven). The repo-copy fixture in `tests/conftest.py` skips
    `*.egg-info` for the same reason.
  - A tree-wide pin in `tests/test_test_suite_contract.py` names the only
    three files allowed to spawn `python -m build`, so a new in-place build
    site reds instead of re-opening the race.
  - The release matrix and `scripts/wheel_smoke.py` still build in the live
    tree: hand-run release-ladder steps, run alone by design, and now say so.
- **A Node adopter's defaults are read from the repository, not from a
  Python-shaped guess.** Driven on an init'd Node/Astro tree, every one of
  these was wrong before:
  - The fingerprint read `.mjs`, `.cjs`, `.mts` and `.cts` sources as no
    language, and an Astro page as no UI. `.astro`, `.vue` and `.svelte` are
    their own languages now, and the UI probe derives its suffixes from the
    one language map.
  - The hooks' source set had none of those formats either. A root
    `index.mjs` was written with no plan, the write count behind the stop
    gate's docs and review checks never started, and Stop allowed every
    turn. `espalier.toml`'s new `source_extensions` key adds your own.
  - `/preflight` linted with whatever `ruff` was on PATH (on a Node tree, the
    harness's own vendored `tools/cc/`, leaving a `.ruff_cache`) and tested
    with a PATH `pytest` before `npm test`. Steps 1 and 2 now run your
    declared lint, test and build first (`[extra_actions]`, then what the
    fingerprint infers) and name the gate they ran; the PATH probes run only
    when nothing is declared, each behind its own project file (a Python
    project's PATH ruff now leaves the vendored `tools/cc/` out and writes
    no cache).
  - The workflow profile allowed `Bash(npm *)`, so `npm install`, `npm exec
    --yes` and every script ran unprompted, and it shipped the pytest, ruff
    and black rules to every repository. Derived rules are narrowed to the
    command's prefix (`Bash(npm test *)`, `Bash(npm run build *)`), and the
    Python rules render for a Python repository only. A command declared in
    `[extra_actions]` is allowed as written, and one that runs code or a
    package by name (`python -c`, `npm exec`, `npx`) is never widened. An
    existing settings.json keeps the rules it has, since the merge never
    removes one; `doctor` now warns about the broad rule and names the
    delete.
  - The stop gate's review and docs checks were relieved only by agents
    named `code-reviewer` and `docs-maintainer`. `espalier.toml`'s
    `code_review_agents` and `docs_refresh_agents` name your own (a built-in
    agent is refused), the deny messages say so, and a docs run that edits
    `.mdx` counts. The deployed reviewer and test-writer can run your test
    command. A value the hooks would ignore, or one of these keys written
    below the `[extra_actions]` header, is named by `doctor`.
  - The plan recommended seven agents no release ships, and doctor's
    headline on a healthy UI, API, ML or ops repository was that
    recommendation. They are now suggestions `init` prints once, and doctor's
    headline is the next step, never information.

- **Hook warnings now reach Claude; until now most went to Claude Code's debug
  log and nowhere else.** A hook that exits 0 has its stderr written to the
  debug log only -- Claude never sees it and the transcript never shows it --
  and that is where every SessionStart boot warning went (a stop-time test
  override that will not start, an unresolvable hook interpreter, nested-repo
  litter, freshness, the maintenance-mode explanation, integrity drift detail),
  along with `post_write_check`'s findings (a truncated settings file, a syntax
  error under `tools/cc/`, placeholders, and the memory autoprune's line naming
  the Session Log rows it archived, the only place they are named) and
  `reflect_trigger`'s note that the reflect pipeline had gone dark. The
  SessionStart banner now carries those lines as a bounded `--- WARNINGS ---`
  block at the top of its body, and the two PostToolUse hooks fold theirs into
  the `additionalContext` of the one JSON object they print at the end of a
  run; stderr keeps a debug copy of each. Where an event has no quiet channel
  to Claude -- PostCompact, Stop, SubagentStop, ConfigChange -- and for the
  eight reporter hooks' crash guards, the line is a once-a-session
  `*_failed_open_*` audit record that `/status --log` counts: the Stop gate's
  Gate 1 skips (a fingerprint whose test paths are all gone, a suite killed at
  the time budget, an unreadable fingerprint, a misspelt
  `ESPALIER_STOP_GATE`), `post_compact`'s capture faults, `subagent_stop`'s
  record failures, `config_guard`'s failed scan, `plan_guard`'s ignored
  `plan_exempt_prefixes` entries, a skipped discard snapshot and an unlocked
  integrity read. **If you opted into `ESPALIER_STOP_GATE=full`, a suite that
  outgrows the 60-second budget is killed and the Stop allowed, as before --
  it now leaves a record saying so.** The fail-open voice gate counted a
  stderr line as speech, which is how this stayed green; it now splits seen
  speakers from stderr-only ones and walks every stderr line in the hooks,
  each paired with a seen speaker in its block or declared
  (`# voice: <kind> <reason>`) as the debug log's on purpose. The hooks
  reference's "What you see" blocks are relabelled to say which channel each
  line reaches, and the docs that said `post_compact` re-injects context after
  a compaction now say what does: it captures the summary, and the
  SessionStart banner Claude Code re-fires after a compaction re-orients.

- **The hook type gate checks the same platform on every host.** `[tool.mypy]`
  pinned the interpreter version but not the platform, so on Windows mypy
  checked the hooks against the Windows standard library, where `os.getuid`
  and `fcntl` do not exist. The hooks guard both at runtime, so the code was
  correct, but `mypy tools/cc/hooks/` reported an error there that no CI cell
  could see. The tier's type line and `/preflight` Step 1 read red on every
  run from a Windows clone. `platform = "linux"` now sits beside
  `python_version`, which matches what every CI cell already checks.
  `tests/test_mypy_config_stays_near_strict.py` now asserts both settings.
  Because the pin makes mypy skip every `sys.platform == "win32"` branch, the
  same test now fails if any such branch in the hooks holds code that needs
  typing. Today none does.
- **A handoff from a linked worktree refuses before it appends anything, and
  the landing check reads a linked worktree of the operator's tree as that
  tree.** `after-goal` roots its resume index, archive leg, record snapshot and
  landing check at the checkout it runs in, and a worktree checks out tracked
  files only: driven in a scratch worktree, the phase appended the index and
  the leg before the snapshot refused, and the retry was refused by the
  summary-state check, whose advice looped back into the same refusal. It now
  refuses first, naming the main checkout and where the session's notes live.
  The landing check's operator-tree tell, the gitignored goal file, never
  checks out into a worktree, so three arms read the operator's own worktree
  session as a reviewer's clone and demoted their reds to notes; the main
  checkout's tell now counts for its worktrees, the codename arm names the
  file to copy in and from where, and the candidate-key arm reads the main
  checkout's log when the worktree has none. A filed row records the suite's
  live-tree package builds staging under xdist, seen once on a required cell.
- **The record merge resolves a criss-cross against a real merge base.** Two
  lanes stacked on one machine, each caught up with the other machine's landed
  lane and the first then merged, give the second lane's next catch-up two merge
  bases, and git's stage 1 is then a virtual base carrying `Temporary merge
  branch` markers neither side wrote, which the shape rules could only refuse
  (the memory file as a conflict outside the Session Log rows, the probes roster
  as not JSON; one such refusal was resolved by hand on 2026-10-05). The merge
  now resolves each record file against every real merge base and lands only
  where they all agree, naming the base in the report; a disagreement, or a
  conflict any base refuses, is refused naming every base and its reading, the
  tree left clean, because the first base that happens to resolve can be the
  one that never had a row and would bring its retired probe back. One merge
  base behaves exactly as before, and a git that cannot name the bases says so
  in the report.
- **The record snapshot refuses to run from a linked worktree, naming the main
  checkout.** A worktree checks out tracked files only and the record's whole
  payload is gitignored, so a snapshot rooted in one reported every record root
  absent, recorded nothing and said nothing (measured in a scratch clone: the
  main checkout includes its record files, the worktree's copy of the script
  includes none, exit 0). Every mode now refuses at exit 2 with the main
  checkout and the `--repo-root` way past; the main checkout of a repo with
  worktrees still runs.
- **`init` no longer wires an interpreter that answers `--version` and cannot
  start, and `doctor`, `--rewire-interpreter` and the enforcement claim stop
  vouching for one.** `--version` is answered before an interpreter
  initialises, so a broken install passes it: a `python -m venv --copies` made
  from inside another virtualenv on 3.10 records that virtualenv as its
  `home`, prints `Python 3.10.x`, and dies importing `encodings`. The resolver
  wired such a `python` into every hook command on its banner alone, every
  hook then exited outside the `{0, 2}` the hook protocol reads as a decision,
  and every blocking guard failed open while `init` reported success. A
  candidate whose banner reads as a Python 3 must now also start: one probe,
  `-I -c 'import sys'` under the banner probe's two-second timeout, run once
  more only if it times out (isolated, because settings.json outlives this
  shell's `PYTHONHOME` and `PYTHONPATH`), and skipped only for the path the
  running interpreter was started as. One that cannot start falls through to
  the next candidate, and when nothing else validates, the warning quotes its
  exit status and last line. The shared floor check runs the same probe, so
  the `py -3` launcher, the `--rewire-interpreter` target and its staleness
  test, and the spelled remedy hold to it: a tree an older `init` wired to
  such an interpreter is repaired by `init . --rewire-interpreter` instead of
  told there is nothing to do. `doctor` names the start failure instead of
  calling the interpreter below the floor (the opposite consequence: a
  below-floor 3.9 runs every guard), points the rewire at whichever name
  starts or says it has no target yet, and calls `python3` working only when
  it starts; the enforcement claim is withheld and says why. The cost is one
  more interpreter spawn wherever a banner passes: per candidate in `init`,
  per wired site in the rewire. The hook-side floor check, paid on every
  SessionStart, still reads the banner alone, and now says it may warn but
  never decide what to wire.
- **A `bypassPermissions` default in your settings no longer locks every
  tool call.** It was classed as a hook kill-switch beside
  `disableAllHooks`, so a bypass default in your personal
  `.claude/settings.local.json` made `write_guard` deny every call, Read and
  Glob included, and `config_guard` refuse every unrelated settings change,
  until you edited the file outside the session; `doctor` failed it as
  "governance kill-switch active". But Espalier's hooks keep running and
  denying in bypass mode -- it turns off Claude Code's permission prompts,
  not the hooks -- so it is now a posture, not a kill-switch: the session
  banner names it on a `Permissions:` line, `doctor` names it on an info line
  instead of failing, the selfcheck contracts pass it, and `config_guard` no
  longer refuses settings changes over it. A session's write of one into
  either settings file is still denied by `write_guard`'s protected-zone check
  (off under `ESPALIER_MAINTENANCE_MODE`, when the default is named at the
  next session start instead), and a committed bypass default still fails CI.
- **A freshly initialised repo no longer reads as drifted to reflect.**
  On a new `espalier init`, the reflect pass that runs on every tenth
  source write and the `/preflight` reflect step both listed six docs
  `init` itself seeds as orphans, any unlinked `.claude/rules/` file
  (which Claude Code loads without a link) as an orphan too, and
  `/preflight` counted dozens of empty sections that were its heading
  parser reading a `# comment` inside a shell fence, an indented example,
  or a parent heading followed by its subheading. Both halves now skip
  `init`'s stamped seeds and `.claude/rules/` for the orphan check only
  (links and residue are still checked), headings are read the CommonMark
  ATX way (a fence or a four-space indent is content; a section is empty
  only when the next heading is the same level or higher), and the advisory
  the model sees names the first findings instead of giving counts alone.
- **`/handoff` commits only the files it wrote; a change you staged and did
  not commit stays staged instead of shipping under the memory subject.**
  Step 5 staged `ESPALIER_MEMORY.md` by path and then ran `git commit` with
  no paths, which commits the whole index: a change somebody staged before
  the handoff (one you held back from `/commit`, which leaves an earlier
  staged change staged, or a parallel session's) rode into the
  `docs(memory):` commit, and step 8 pushed it with auto-merge armed, reviewed
  by nobody. The step-5 fence now names the same paths on the commit line as
  on the add line, and says what `/commit` says: a change staged before you
  started stays staged and is not unstaged (with `handoff_push` on it keeps
  the tree dirty, which the push refuses, so the summary names it for its
  owner), and a merge, a cherry-pick or a rebase in progress stops you before
  the add line, since git refuses a path-limited commit in the first two and
  anything staged inside a merge is deleted by `git merge --abort`. The
  source tree's `scripts/handoff_mechanics.py after-memory-row` commits the
  same way, and refuses with exit 2 before it prunes, finalizes or stages
  when one of those operations is in progress. `/implement-pack` step 10
  said "a plain `git commit`"; it now gives the same fenced lines, stops
  listing the integrity manifest (gitignored and per-install) as a path to
  stage, and says that a file you stop tracking but keep on disk cannot ride
  a path-limited commit, which tracks it again, so it lands on its own
  (`/commit` says so too); step 12's "land it with the pack's commit" names
  the amend by path. The amend that fixes a red landing check (`/handoff`
  step 7c, `/commit` step 4, and the landing check's own remedy text) was a
  bare `git commit --amend`, which takes whatever is staged into the commit
  even when only the message changes; it is now `git commit --amend --only`
  (with `-F <file>`, since from a tool call the editor keeps the old
  message), or `git commit --amend -- <the paths you fixed>`. The real-git
  test that drove `/commit`'s fence now drives every shipped body that
  commits beside an owner's staged change and staged untrack, a census fails
  on a commit in a body it does not drive or one that can take what it does
  not name (fenced, chained, prefixed or in prose), and every amend a shipped
  body teaches is driven the same way. A re-init or `upgrade --execute`
  deploys the three bodies.
- **The sessions class's two windows-latest reds.** `tests/test_hooks.py`'s
  clear-retire row and `tests/test_task_router.py`'s heartbeat row assert the
  hook's parent is the test process; a Windows venv's `python.exe` is a
  redirector that launches the base interpreter as its own child, so each
  spawned hook recorded a fresh redirector pid (the Windows box, 2026-10-06).
  Both now spawn through `tests/_interpreter_hosts.py::HOOK_PYTHON`, the base
  interpreter when one is recorded (CPython's own bypass, bpo-35797), and the
  clear-retire row's failure names the parent it saw. `tests/test_session_banner.py`'s
  sibling-cwd row built its tail-capped case with a literal `/` split, which on
  Windows named a different directory (red in CI at #104 and #105) and on POSIX
  collapsed to the plain root; it now builds a root longer than the cap and
  checks the written record is capped. The rows pass on such a host; the
  feature stays NOT REACHED there (the sessions pack's reach row), since a
  live Claude Code window with a launcher between `claude` and the hook
  records that launcher's pid. The review round switched the two modules' nine other
  `tools/cc` script spawns to the same constant (no mixed form to copy), added
  a derivable pin in `tests/test_test_suite_contract.py` (a module that asserts
  on a parent pid spawns scripts through it) and an identity test for the
  constant, and made the banner test's negative assertions name the sibling,
  so an empty line cannot pass them.
- **The heartbeat's self-healed session marker records the hook's parent pid,
  and a touch repairs a marker that has none.** `task_router.py` touches this
  session's marker on every prompt and, where the marker is missing (a session
  from before wave A landed, or one the seven-day prune swept), writes it; that
  stub carried `pid: null`, an unknown start and nothing else, so the
  `clear`-time retirement, which matches markers by the window's pid, could
  never retire it, and the banner named the operator's own predecessor as a
  live sibling for up to four hours (measured 2026-10-05: `32ec76f5` survived
  a `/clear`). The heartbeat now hands `touch_session_marker` its parent pid
  and the payload's `cwd`: a self-healed marker records both (source
  `heartbeat`), and the first touch that knows its window rewrites a pid-less
  marker once, keeping the start, `cwd` and `source` it held (an unreadable
  marker reads as pid-less and comes back readable); a recorded pid is never
  overwritten, and a touch with no pid repairs nothing. A marker already
  pid-less whose session has since been cleared is never touched again and
  ages out of the four-hour live window. Both writers of the marker's `cwd`
  now read it through one resolver (`hook_cwd`, hoisted from
  `session_start.py`, whose private name stays as an alias), so a self-healed
  marker's path compares with the resolved root the way a SessionStart-written
  one does, instead of rendering a symlinked spelling of this checkout as a
  worktree on the sibling's line; and the writer records anything but a
  positive int as `null`, the one rule the repair and the retirement read by.
  The conftest guard's hole list loses the entry this closes: a prompt-hook
  run on the live tree is now attributable by pid, like a SessionStart's.
- **The reflect pass no longer reads a Claude Code worktree under
  `.claude/worktrees/` as part of your repo.** The surface walk in
  `tools/cc/reflect_protocol.py`, the copy the every-tenth-write reflect hook
  and `/implement-task` run, descended into any nested checkout, and a
  worktree's `.git` is a file the walk never tested for: on a checkout holding
  five worktrees it read 1857 files and raised 1055 findings, nearly all of
  them phantom orphans and broken links inside the worktrees, where the
  engine's walk read 184. Both of its walks now prune any subdirectory
  carrying a `.git` entry of any kind -- a directory, a worktree's gitlink
  file, or a `.git` symlink whose admin dir has moved, which its
  folder-router walk had still entered -- through one helper, the rule the
  engine's walk already used; the same checkout now reads 184 files and 2
  findings on both.
- **A lesson promoted from `/handoff` or `/reflect` on your repo is proposed
  into the catalog `/recall` reads back, and the report prints where.** The
  candidate pass applied the Espalier source repo's distribution model on
  every tree, so a lesson on an adopter's repo was proposed into
  `docs/FAILURE_MODES.md`, a catalog `/recall` indexes only on the source
  repo; filing it there also changed the seeded copy's digest, so `init`
  stopped refreshing that file. The pass now reads which tree it runs on: off
  the source repo it proposes `docs/SHARP_EDGES.md`, or keep local for a note
  about a person (a handle, an address, a co-author credit, a stated
  preference), and a lesson naming a task pack or the harness is still the
  adopter's own; the source repo keeps its table. When that check cannot run,
  the adopter table applies, and a `ROUTING:` line under the candidate count
  says which table the targets come from and when the check failed. Each
  candidate prints one `proposed: <tier> -> <target>` line, a keep-local one
  naming the phrase it matched, and the `/handoff` and `/reflect` bodies defer
  to it instead of restating a table that was wrong on every adopter tree.
  Misreads fixed on every tree: a dotted or called decorator such as
  `@pytest.fixture`, an npm scope such as `@types/node`, a version pin such as
  `actions/checkout@v4.2.1` and a `git@` remote no longer read as a person,
  and a bare "trailer" (an HTTP trailer) no longer reads as a commit
  attribution. A bare `@Override` or `@media` outside a code span still reads
  as a handle; the printed match shows it.
- **The packaged slash commands show their purpose in your slash menu
  again, not the managed-marker comment.** Seventeen of the eighteen
  packaged commands opened with a prose line and no frontmatter, so
  `espalier init` put the `<!-- espalier:managed ... -->` marker on line 1,
  and Claude Code, which takes a frontmatter-less command's first non-blank
  line as its description, listed that comment for `/commit`, `/handoff`,
  `/preflight`, `/status` and the rest, in the slash menu and in the model's
  own listing. Each now carries a `description:` frontmatter equal to its
  opening paragraph, so the marker lands after the closing delimiter; the
  CLAUDE.md command table and `cc/COMMANDS.md` read the same text as before.
  A re-init or `upgrade --execute` regenerates the seventeen deployed copies.
  A copy whose marker line you deleted by hand reads as your own file and is
  left alone: put the marker line back, or delete the file, and re-run
  `espalier init`.
- **The suite no longer drives the SessionStart hook on the live tree, and a
  conftest guard reds the test that does.** Four test sites ran the deployed
  hook rooted on the checkout itself: `tests/test_session_start_toc_gating.py`
  (two, with session id `test`) and
  `tests/test_session_start_maintenance_warn.py` (two, with none). Every such
  run is a non-continuation SessionStart on the operator's own tree: it
  rewrites `.espalier-state/session_started` and clears the running session's
  gate counters (measured 2026-10-05: the live stamp moved under one run of
  the file), and since the per-session marker landed the first pair left
  `.espalier-state/sessions/test.json`, which the operator's next banner read
  as a live sibling session for four hours ("2 other sessions ... test
  (started 23 min ago)"). The four sites now drive `self_host_tree_copy`, a
  private per-test copy of `initialized_repo_root` (the `driven_banner`
  shape; copied from the fixture rather than REPO_ROOT, so a build beside the
  suite cannot false-red it), and both helpers refuse the live root outright
  and send a session id, so a re-root leaves the one trace the guard can
  attribute. The guard, `_no_live_session_markers` in
  `tests/conftest.py`, is autouse and per test: a marker that appears or is
  rewritten under the live sessions directory during a test and records this
  pytest process as the hook's parent pid is that test's by construction, so
  the guard names it, removes it and fails; the operator's own markers
  (another pid) and a heartbeat stub (no pid) are not attributable and are
  left alone, the same rule by which `_no_live_tree_writes` leaves the rest of
  `.espalier-state/` unwatched. Two holes are named in the guard's comment: a
  SessionStart sent without a session id writes no marker (hence the helpers'
  root assertions), and a prompt-hook run on the live tree self-heals a marker
  with no pid, which only a hook-side change (the stub recording its parent
  pid) can make attributable. Driven red on the unfixed pair (two teardown
  errors naming `test.json`) before the move; all twenty-nine SessionStart
  runs across twenty-five tests in `tests/test_hooks.py` pin
  `CLAUDE_PROJECT_DIR` to `tmp_path` and were left alone. Not a ledger row: the guard is the oracle
  (`docs/STANDING_PRINCIPLES.md` section 18).
- **The release-readiness gate no longer reds on every pull request, and
  the two sites that bounded a test leg at twice a recorded figure without
  saying so on a green day now say so.** The gate's not-slow leg figure
  (`scripts/release_check.py::NOT_SLOW_LEG_MEASURED_S`) read 620 s, sized on
  the self-host box, while the gate's ubuntu-latest runner measured 734 to
  1153 s across nine completed legs on 2026-10-05 and a tenth was killed at
  the 1240 s bound; the figure is now the slowest completed runner reading,
  1153 s, so the derived bound is 2306 s. The drift went unseen through a
  week of green runs because only the release matrix's stage 01 carried the
  on-green NOTE: `check_tests_pass` now appends the same NOTE to a PASS whose
  leg exceeded the figure and raises it as a `::warning` annotation under
  GitHub Actions, where a green job's log is collapsed; `espalier
  pre-release` reports one under a new `notes` key when its own test layer
  outgrows `NOT_HEAVY_E2E_LEG_MEASURED_S` (every command record there now
  carries its `duration_s`). The matrix's stage-02 ceiling
  (`scripts/final_release_matrix.py::_SUITE_BOUND_S`) stays a hand-sized
  literal under `DEF-918`.
- **`upgrade` no longer offers to overwrite a file of yours.** A `.claude`
  file of your own at a name Espalier also ships was called an edited copy
  of Espalier's, and the one remedy offered -- add the marker line -- hands
  it to the next `upgrade --execute`, which replaces it. `upgrade` now names
  what it keeps on both of its paths without presuming who wrote it, says
  what the marker would do, and names a command of yours that one of
  Espalier's skills replaces (or a skill of yours that replaces one of its
  commands). `espalier audit` and `/smoke` warn about such a clash made
  after install.
- **Uninstalling from inside a Claude Code session no longer locks the
  session.** `clean-generated --execute` deleted the hook scripts the
  session was still wired to, and every later prompt failed with `can't
  open file` until a restart nothing asked for. Run from a Claude Code
  session, `--execute` now only unwires the hooks and asks for a second
  run, which deletes; every `--execute` ends with a reminder to restart any
  session open on the repo.
- **Removing a temp directory works on the PowerShell tool.** A forced
  recursive remove of any absolute path was a hard stop there, with no
  re-issue and no maintenance-mode relief, so a removed git worktree under
  `C:\tmp` (whose read-only object files need `-Force`) or a scratch tree
  under `%TEMP%` could not be deleted, while `rm -rf /tmp/x` on the Bash
  tool has always drawn one confirm-by-re-issue nudge. A literal path
  strictly below a scratch root (the temp directory `TEMP`, `TMP` or
  `TMPDIR` names, a drive-root `tmp` or `temp`, a POSIX temp root) now draws
  that same nudge, forced or not. The temp root itself (however spelled,
  `C:\tmp\.` included), this project's checkout or your home directory under
  it, a link that resolves onto one, a variable, a wildcard and a `..` step
  are still refused, and a `TEMP` that names your home, a directory above it,
  a drive root or a top-level system directory such as `C:\Windows` makes
  nothing scratch.
- **`espalier doctor` stays green after ordinary work.** The drift check
  compared census the fingerprint is documented to ignore: the five newest
  commit subjects and a ratio, per-language file counts, large-file sizes and
  line counts, the per-page docs listing and each signal's evidence, so an
  ordinary commit, a lock-file bump on a dependency update or a new docs page
  turned `doctor` yellow and made `espalier diff` exit 1. The comparison now
  reduces each of those fields to the signal it carries (a format, a name set,
  a path set, a presence) and names every reduction in the diff result's
  `ignored_local_only_keys`; a new language, a new CI provider, the first docs
  page, the first large file and a change of primary language still flip. A
  key an older release saved that the current schema no longer declares is
  not drift either, nested agents, hooks and config included. The saved
  report keeps every field, and the `fresh_fingerprint` / `saved_fingerprint`
  blocks `espalier diff` prints are now the compared (reduced) views, so a
  script reading `languages` out of that output sees an object with `primary`
  and `names` rather than a list; read `reports/repo_fingerprint.json` for
  the raw fields. The language order the fingerprint saves now breaks ties
  by name, so the same tree fingerprinted on two machines agrees. The matrix
  is proven on a TypeScript-first tree.
- **A scan check that did not run on your tree no longer reads as a clean
  result.** On any repository other than the Espalier-Harness source, the
  five scanners that police Espalier's own registries and vocabulary
  (subprocess, filesystem, magic-depth, retired-vocabulary and encoding
  contracts) stand down, and `espalier scan` used to print `0` for each,
  store the zeros in `reports/scan_summary.json`, and say they had not run
  only when nothing else was found; after a few runs the credibility advisory
  called all five wallpaper. Now the counts line prints `n/a` for them, a
  `Not run:` line names them on every run, each placeholder report carries
  `"ran": false` and the reason, the summary lists them under `not_run`, and
  their telemetry rows stay out of the credibility budget. `/scan` marks all
  five self-host only, and `/smoke`'s Provenance line gains `SKIPPED` for the
  census that stands down on your repository, which it used to report as
  `OK`.
- **The cmd.exe maintenance-mode relaunch the harness prints now turns
  maintenance mode on.** cmd.exe keeps the space before `&&`, so
  `set ESPALIER_MAINTENANCE_MODE=1 && claude --continue` handed the session
  `1 ` (driven on Windows), and every reader compared the value to `1`
  exactly -- an operator who followed the deny's remedy was relaunched into
  the same deny, with no MAINT indicator. Every reader now strips the value
  through one predicate (the statusline keeps a one-line copy), a test fails
  on any new raw comparison, and the printed remedy, the generated
  `CLAUDE.md` and every doc copy spell the quoted form
  `set "ESPALIER_MAINTENANCE_MODE=1" && claude --continue`, which sets exactly
  `1`.

- **`write_guard` refuses a harness variable set inside `cmd /c` before a
  Claude Code launch, from Bash and from PowerShell.** cmd.exe's `set`
  changes the cmd process's environment for every later statement, and
  neither env-prefix rule knew it, so wrapping the maintenance-mode remedy
  in `cmd /c ... claude -p` started a nested session with the protected-zone
  check off. The opener is read at a command position (a mention inside
  prose stays allowed) and its program is split on cmd's separators in code;
  a `set` before any other command (`&& pytest -q`) is still allowed. The
  bypass benchmark carries the six reaches as new attempts.

- **Parallel hooks and subagents on Windows stop losing what they write.**
  Every file lock the harness takes was `fcntl.flock`, so on Windows the
  blueprint chain, the plan tracker, the write and speed-bump counters, the
  audit and telemetry logs, the integrity and freshness manifests and the
  review corpus were all written unlocked -- and parallel tool calls or
  subagents finishing together are concurrent writers inside one session.
  Driven on a Windows host: ten parallel blueprint records kept 3 to 5
  entries, some dying on a `PermissionError` that SubagentStop reported
  silently; eight counter writers kept 14 of 200 increments; concurrent
  appends lost lines. One lock primitive now serves every site --
  `fcntl.flock` on POSIX, `LockFileEx` on Windows, exclusive or shared --
  with a copy for `tools/cc/` and the hooks and a twin for the engine, and
  each atomic writer retries the one refusal Windows gives a rename onto a
  file another handle holds open, for about a second. The audit append now
  flushes inside its lock (the buffered line used to reach the file after the
  unlock), and falls back to an unlocked append rather than dropping the line
  when a filesystem cannot lock.
- **A stock Windows interpreter runs `init`, `/handoff`, `/read-summary`,
  `/reflect` and `/design` to completion.** Without UTF-8 mode, a Windows pipe
  (Git Bash, CI, Claude Code's Bash tool) encodes output through the ANSI code
  page, so a repository named outside it made `init` stop half-deployed --
  hooks wired, ignore block never written -- and call it "malformed data"; an
  arrow in a commit subject, the working summary or a recorded decision made
  the `/handoff`, `/read-summary` and `/reflect` CLIs exit 1, and every
  `/handoff` appended bytes that were not UTF-8 to `cc/_working_summary.md`;
  the `/design` dead-config pass died decoding the shipped bodies; and the
  review workflows' save step died on a curly quote in a finding, after the
  whole review had run. Every shipped CLI (the event hooks aside, whose output
  is ASCII JSON) now reads stdin and writes stdout and stderr as UTF-8 before
  it does anything else (`espalier/_text.py` and `tools/cc/_json_safe.py`
  each carry the helper; the scanners, `ci_guard` and the hook-directory CLIs
  inline it); every Python body a shipped command, agent, workflow or seeded
  doc runs names the encoding of its reads and pins stdout before it prints
  operator text; and an encoding failure that still reaches `espalier` is
  named as one. Two contracts hold it: every entry point pins its streams
  first, and every shipped Python body reads with an encoding and prints
  through a pinned stdout.
- **A Windows host whose only working Python is the `py` launcher gets
  working guards.** On a python.org install that left PATH alone (the
  installer's default) and with `python`/`python3` as Microsoft Store
  aliases, `init` wired every hook to `python`, which only printed a Store
  prompt, so every guard failed open. `init` now picks the interpreter by
  what it answers: it tries `python`, then `python3`, then `py -3`, and
  writes the launcher as `command: py` with `-3` leading the args. `doctor`,
  CI's guard and `merge-settings --repair` accept that wiring instead of
  calling it dead and replacing it; `init --rewire-interpreter` moves a
  site to or from the launcher with its flag; the SessionStart host line
  names `py -3`; the `/preflight` steps and the review workflows' persist
  command pick the first interpreter that answers instead of the first
  name that resolves; and the rendered CLAUDE.md rule says to fall back
  when a name prints no Python 3 version, not only on `command not
  found`. A wiring of `py` with no version flag, or with `-2`, now reads as
  unwired: without `-3` the launcher follows the hook's `python3` shebang
  to whatever answers on PATH. With `ESPALIER_STOP_GATE=full`, a hook
  interpreter that has no pytest now skips the test gate with a note
  instead of blocking every Stop.
- **A repo that already commits its own task packs keeps them stageable.**
  `espalier init` wrote `/task-packs/*` even where the repo tracks packs of
  its own (a harness of its own, such as Trellis), so every new pack
  silently stopped staging. Such a folder is now left to you, and `init`
  says so; a placeholder such as `.gitkeep` does not count. A block an
  earlier install wrote over versioned packs is never edited: `init`,
  `--dry-run`, `upgrade` and `doctor` name the line to delete and every
  file deleting it would unhide, because one tracked file is too weak a
  sign to unhide the rest. Uninstall no longer keeps an ignore rule for a
  file git tracks. `/implement-pack` decides the move to `Done/` by whether
  the pack is tracked and whether `Done/` is ignored.
- **`init` names what it keeps and what it replaces.** The summary lists
  every file of yours it kept (a command of the harness's name among
  them) instead of a bare count, and names an adopter command a harness
  skill of the same name replaces, and the reverse (Claude Code runs the
  skill). `init --dry-run` now reads the deploy's own classifier: it says
  which existing files it keeps rather than claiming to write them, whether
  your `.claude/settings.json` would be left without hooks, what it would
  do to `.gitignore`, and the forward ledger and onboarding rows it would
  seed. `upgrade` no longer says "nothing to do" under a pending
  `.gitignore` report, and the entries `init` writes to `.gitignore` are
  named.
- The stop-time test override's reason now says whether the program did
  not resolve or resolved and still could not start; the plain pytest
  branch allows a spawn failure with a record instead of a silent green;
  the write counter's read-only-state-dir branch reads the counter it was
  asked for (it read the default file's count); the four internal-error
  denials carry their remedy; the stop gate names the test paths it looked
  for when none exist.
- **The banner no longer says an armed merge is "held by the red" when the red
  is not required.** `gh pr list` carries no is-required flag, and one pull
  request merged with three advisory legs red while the tail said the red held
  it. The tail now reads `it merges unless a red check is required (gh pr
  checks N --required says which)`; a conflict still holds, and a behind lane
  keeps its catch-up hint.

- **The Windows portability leg fails loudly when pytest dies without a summary
  line.** A session-level `pytest-timeout` kill
  printed no summary and read like an ordinary red; the `Test` step now keeps
  pytest's own exit code through the `tee` and exits 70 with a `::error::` when
  no summary line is present (`--color=no`, so a forced-colour environment
  cannot hide the line). A parallel run measured 28 minutes against 67 to 90
  serial on Windows, then redded a serial-only wall-clock budget test on macOS
  on its first pull-request run, so the leg stays serial; the split invocation
  that takes the saving safely is a ledger row. The leg's one known red, the
  `fcntl`-only corpus lock, was keyed to the platform until the lock class fix
  below gave Windows a lock and deleted that branch.

- **`espalier doctor` no longer warns on a repository with installed npm
  packages.** The reflection walk was the one markdown walker with no
  directory skip list, so it link-checked every README under `node_modules/`
  and reported a package's broken links as the repository's: 331 of them on
  one adopter clone with 523 packages, every one in a file the adopter does
  not own. `safe_rglob` takes a `skip_dirs` argument that prunes during the
  walk, and one set of package-manager directories (`node_modules`,
  `bower_components`, `jspm_packages`, `.yarn`, `.pnpm-store`) is shared by
  the reflection, `strengthen` and scope-check walkers. Those kept three
  lists and gave three answers about one tree: `strengthen` read a
  workspace's nested `node_modules/`, and it and the scope walk both read
  `bower_components/`. `vendor/` stays scanned, since a Go repository commits
  it.

- **`init` ignores the plan tracker's state and the discard snapshot log, and
  appends in the file's own line ending.** The block `init` adds to
  `.gitignore` left out three files the deployed code writes under `cc/`: the
  execution plan, its lock and the discard checkpoint's snapshot log. A plan
  left `in_progress` could be committed, and the plan gate in every fresh
  clone of that repository was then open before any session had opened a
  plan. The three are entries now; `upgrade --execute` delivers them to an
  installed tree, and an entry your own rules already cover (a `*.log` line
  covers the snapshot log) is not repeated. If you have already committed
  one of them, the entry is withheld as before, and the message now says to
  untrack it (`git rm --cached`) instead of offering to keep it. A test
  renders the block and asks git about every file on the roster of files the
  deployed code creates. The same append wrote the platform's line
  ending, so on Windows every appended line landed as CRLF under an LF file;
  it follows the file's own ending now, and LF for a new file.

- **`upgrade` on a version-current tree sees an `espalier.toml` edit.** It
  said "nothing to do" after an action or a zone was added to the file, while
  `doctor` on the same tree called the saved plan changed, because none of
  its checks looked inside the plan. It now rebuilds the plan from the saved
  fingerprint and the file on disk and compares the actions and the two zone
  lists with the saved plan, so an action or a zone added, changed, removed
  or suppressed is named in the preview and applied on `--execute`. Nothing
  is walked: a fresh fingerprint measured about a second on a tree of ten
  thousand files, too much for every run to pay. `examples/espalier.toml`
  says which verb applies an edit to which key.

- **An `[extra_actions]` entry that is not a list of commands is dropped and
  named, by every verb.** A top-level key written below the `[extra_actions]`
  header belongs to that table. `lane_count = 5` there crashed `init`,
  `fingerprint`, `doctor` and `upgrade` with a `TypeError` that named no
  file, and a string there became an action with one command per character,
  saved into the plan without a word. The loader now drops such an entry with
  a warning that names the file, the key and the fix (move it above the
  header), and keeps the well-formed entries beside it. An unknown top-level
  key is still ignored silently.

- **The multi-step banner no longer fires on read-only prompts that mention a
  build.** The prompt router carried a bare `build` keyword, so on a site or
  app builder "check the build output for broken links" drew an instruction
  to open an execution plan: seven of eight read-only prompts in an adopter's
  labelled set, one of eight now. `build a` and `build the` still match the
  task's verb. A prompt that opens with a read-only imperative (check,
  verify, look at, summarize, compare, show, list, review) is treated like a
  question; a command reference (`npm run migrate`, a backtick span) is not
  read as task scope; and the quick-fix and question words match as whole
  words, so `typo` inside `typography` and `how` at the head of `however` no
  longer suppress a genuine multi-step prompt.

- **`/commit` stages what was reviewed and approved, by path.** It reviewed
  with `git diff`, which lists modified tracked files only, then staged with
  `git add -A`, which also takes every untracked file that is not ignored:
  on a dirty tree the commit carried an owner's work in progress and the
  harness's own runtime state under a message approved for one change. Step
  1 now lists untracked files, step 3 presents the path list beside the
  message and the approval covers both, and step 4 stages and commits that
  list and nothing else (the paths are on the commit line too, so a change
  someone had already staged stays staged and uncommitted). A deleted file
  belongs on the list. An untracked path under `cc/`, `.espalier/`,
  `.espalier-state/` or `reports/`, or `.claude/settings*`, is left out as
  runtime state; a tracked doc under `cc/` is an ordinary file. `/handoff`
  states the same rule. The message template is unchanged: it still
  prescribes conventional-commit types whatever your history uses.

- **The stop-time test override runs at the repository root and blocks when
  it cannot start.** `ESPALIER_STOP_GATE_TEST_CMD` ran in whatever directory
  the hook process was started in, so a relative test glob could match
  nothing, exit 0 and allow a Stop over a failing test. And a command that
  could not be started allowed the Stop with one stderr line and no audit
  record: on Windows that is the plain spelling of any Node command, since
  `npm`, `npx` and `pnpm` are `.cmd` shims a process started without a shell
  does not find, so a gate armed with `npm test` was green on every Stop.
  The spawn failure now blocks, names the token and the platform's remedy,
  and writes a `stop_blocked_pytest` record with the rule
  `GATE_ENV_OVERRIDE_SPAWN_FAILED`. **If you armed the gate with a
  command that never started, the first Stop of each session will pause until
  you respell it.** Once a session and not every Stop, because the variable
  is read at launch and nothing in the session can repair it: blocking every
  turn would have kept the docs, review and blueprint gates from running at
  all. (The shim is resolved for you and the banner's Warnings block names an
  override that will not start since the spawn chokepoint above, so the plain
  `npm test` needs no respelling.)

- **The `Bash(rm -rf /*)` deny rule is retired from every profile.** A trailing
  `*` in a Claude Code permission rule is a prefix match with no literal
  spelling, so the rule written for the root glob wipe denied every recursive
  delete of an absolute path, in every permission mode, with no reason shown --
  right after the CP-RMRF speed bump had said "re-issue to proceed". The hook
  layer already walls the wipe it was written for. `init` no longer writes the
  rule; `doctor`, `merge-settings` and the `upgrade` preview name the line on a
  settings.json that still carries it, with the fix (delete it, and check the
  local and user-level settings files for the same line), and never remove it.

- **Ledger probes and the shipped workflow bodies run on a host that ships only
  `python`, and still on one that ships only `python3`.**
  `scripts/check_ledger_probes.py` runs a probe spelled with a bare `python3` or
  `python` under the interpreter running the checker (with `-X utf8`, so the
  host's code page cannot decide a verdict), so every probe grades on Windows
  (181 of 188 read UNRESOLVED there before, and every `ledger_row.py` verb was
  refused because the probe it drives first never started); the ledger and its
  probes file are written LF on every platform, and `.gitattributes` pins the
  probes file and the workflow bodies LF; the three review workflows open their
  persist command with the `PY=python3 ... || PY=python` resolver idiom the
  command bodies use, pinned by a contract, instead of a bare name; the
  `DEF-751` probe spawns pytest under `sys.executable`, and a ratchet refuses a
  new probe that spawns a literal interpreter inside its program.
- **Ownership under `.claude/` is the marker's answer.** `doctor` no longer
  calls a clean uninstall a broken install because one skill or command of
  the adopter's own sits under `.claude/`, and its ownership report names
  such files as the adopter's. Two guard false denies: a read-only chain
  holding `sed`, a later `-i` belonging to another command and a protected
  path is no longer refused as an in-place edit (the option run stops at a
  statement separator, spaced or not, with the quote characters outside its
  char class so the match stays linear), and a quoted mention of a guarded
  command beside a nested-quote substitution no longer draws a checkpoint
  (the double-quote closer steps over substitutions). The deployed-doc
  advisory requires git's changed answer for a tracked path, and the
  deployed assets carry no home-path-shaped text.


## [0.8.0b2] — 2026-09-27

The second beta. Since 0.8.0b1 the three fan-out review workflows deploy to adopters
beside the agents, commands and skills, with the review method's memory seeded; the
maintainer release runbook and decision log are readable in the public repository;
the Windows notes state what the fourth Windows walk measured; a `NOTICE` file carves
the pinned third-party documentation excerpts out of the MIT grant; and the
`espalier selfcheck` hint no longer says the package has yet to ship. This section is
the adopter-facing summary of the development record since 0.8.0b1; the record itself
is kept, unedited, in the maintainers' tree.

### Added

- **The three fan-out review workflows deploy to adopters as a fourth `.claude` kind.** `espalier init`
  writes `.claude/workflows/_fanout_audit.js`, `_layered_review.js` and `_convergence_review_template.js`
  beside the agents, commands and skills, each with the managed marker `// espalier:managed` on line 1
  (`export const meta` stays the module's first statement), so `upgrade` refreshes an untouched copy,
  a hand-edited copy is preserved, and `clean-generated` removes them. Claude Code runs each as a
  `/<name>` slash command; they need dynamic workflows on (paid plans), spend dozens of agents a run,
  and ask before running under the manual and accept-edits permission modes. Their prompts read the
  adopter's tree (the layer boundaries the repository's own `CLAUDE.md` and `docs/CONVENTIONS.md`
  declare; a forward ledger only where the repository keeps one). The review method's memory is
  seeded with them: `memory/CONVERGENCE_LEDGER.md` (a skeleton the convergence-critic appends to) and
  `memory/convergence-review-protocol.md` (the method, under the adapt-these-examples header). The
  workflows ship on every release surface (wheel, release zip, `git archive`) and in fusions.
- **The forgery corpus recognises the workflow marker form.** The managed-marker recogniser accepts
  `// espalier:managed` only at the very start of a file; a C-style comment carrying the token on any
  later line, inside a string, or inside a Markdown code fence is still rejected (benchmark class
  BC-026, now eight attempts).
- **A `NOTICE` file at the repository root.** The MIT grant covers this distribution;
  the pinned third-party documentation excerpts under `docs/external/` (one of them
  mirrored into the wheel) are reproduced for verification only and stay the property
  of their owners. `NOTICE` ships in the sdist and in the wheel's licence metadata.

### Changed

- **The maintainer release runbook and decision log are tracked in the public repository**
  (`docs/RELEASE_CHECKLIST.md`, `docs/RELEASE_DECISIONS.md`), readable on GitHub. They stay
  `internal`: neither ships in the sdist, the release archive or the Download ZIP, and
  `espalier init` deploys neither.
- **Filename vocabulary the harness treats as its own internal material** is now the
  `TP-*.md`, `TASK_PACK*.md`, `BLUEPRINT*.md`, `blueprint.md` and `*-atlas.md` shapes plus the
  two release docs; the names of maintainer records that live only in the maintainers'
  archive left every roster and pointer, so an adopter's own like-named file is no longer
  described as something the harness carries. Behaviour on an adopter tree is unchanged.
- **The Windows notes say what the fourth Windows walk measured (2026-09-26):** the
  `PowerShell(...)` allow twins are described as witnessed in a live session, the statusline
  under PowerShell without Git for Windows as known blank (cosmetic; the hooks are unaffected),
  and the read-only-delete note and the protected-zone path-equivalence limits state the
  measured result. The walk's findings are filed in the forward ledger; no engine behaviour
  changed.
- **The package's PyPI development-status classifier reads `4 - Beta`**, matching the
  version; it said `3 - Alpha` through 0.8.0b1, and a test now binds the classifier to the
  version's pre-release stage.

### Fixed

- **The `espalier selfcheck` hint for a runtime-only install** no longer says "once the
  package ships": when pytest is missing it names `pip install pytest` or
  `pip install 'espalier-harness[dev]'`.

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
[0.8.0b2]: https://github.com/Mike-Byrne-AI/espalier-harness/compare/v0.8.0b1...v0.8.0b2
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
