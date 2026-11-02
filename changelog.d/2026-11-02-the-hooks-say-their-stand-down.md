### Fixed

- **The docs gate credits a docs agent with its own changes, not the
  session's.** Gate 2's record listed every markdown file with uncommitted
  changes when the `docs-maintainer` stopped, so one that found nothing to do
  was credited with the edits the session made before dispatching it.
  SubagentStart now keeps a snapshot of the dirty markdown for an agent that
  relieves the docs gate (`.espalier-state/docs_snapshots/<agent id>.json`;
  the id was driven on Claude Code: one bare id on both events, the stop's
  transcript named `agent-<id>.jsonl`), and the stop records only the files
  created or changed since, with `"evidence_scope": "run"`, carrying forward
  an earlier run's files this session that are still uncommitted. A tree whose
  settings do not wire the start hook keeps the whole-tree list, marked
  `"tree"`, and a `subagentstop_failed_open_docs_evidence_unscoped` record says so once a
  session. No snapshot under maintenance mode; the start's git reads are capped
  at 6 s inside its 10 s timeout. The gate's message says that doc edits made
  before the agent ran are not its work.
- **`/status --explain` says whose verdict it gives.** The net line opens
  "Espalier's hooks:", and an `unmodelled` line names the other PreToolUse
  hooks in `.claude/settings.json` and `.claude/settings.local.json` whose
  matcher can reach a file write (a command hook by its command line, an http
  or prompt hook by its type), counts the `permissions.deny` Edit/Write rules
  without matching their globs, and says that user-level, plugin and managed
  hooks are not listed. It used to call any path outside Espalier's zones
  "unprotected", whatever else could deny the write.
- **The deep reflect pass reads an adopter's README.** On a tree that is not
  Espalier's own, every tracked root `*.md` joins both reflect walkers for its
  links (never graded for length or placeholders, never an orphan), so a
  README that links a renamed doc is reported and the doc it links is no
  longer a phantom orphan; a link that leaves the repository, such as a
  badge's `../../actions/...`, is out of tree rather than a gap, and a
  percent-escaped, titled, protocol-relative or `tel:` link is read as what it
  names on both walkers. The lighter
  `espalier reflect` and `doctor` walk keeps an adopter's doc named in
  Espalier's own internal vocabulary (`BLUEPRINT*.md`, `*-atlas.md`).
- **doctor and the session banner tell an adopter that ruff is missing when
  their `/preflight` runs it.** The load-bearing tool check ran on Espalier's
  own repository alone. It now also runs where the adopter's lint step would
  run `ruff` from PATH (an `[extra_actions] lint` whose command starts with
  `ruff`, or a ruff configuration with no `package.json` lint script or
  Makefile `lint` target before it), with an install hint for that tree, through one
  reading on each side pinned equal over a table of trees.
