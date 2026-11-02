### Fixed

- **A `.claude` agent, command or skill whose frontmatter Claude Code will
  not load is named, instead of listed as if it had loaded.** Claude Code
  reads frontmatter as strict YAML and falls back to a line-by-line quoting
  that a Windows checkout's CRLF line endings defeat: an unquoted `: ` in a
  value, or a value opening on `[`, loads with LF and fails with CRLF (an
  agent does not register; a skill or command loses its frontmatter), and a
  ` #` cuts the description under either ending (measured on Claude Code
  2.1.314). `espalier audit` warns about a body that does not load with the
  line endings it has on disk, and `cc/LIVE_SURFACE.md` marks it; the
  post-write check says so when the body is written, once a session, with
  the wording for an LF body that would fail on a CRLF checkout; and
  `espalier doctor` names such LF bodies and recommends a
  `.claude/** text eol=lf` rule in `.gitattributes` where none covers them.
  Quote the value to fix the body itself.
- **The cognitive blueprint is said to live on one machine.** The workflow
  guide and `/handoff` step 1 say the blueprint carries a session's reasoning
  to the next session on this machine, since `espalier init` gitignores
  `cc/blueprints/`, and that a decision which must survive a re-clone or a
  second machine goes in `ESPALIER_MEMORY.md` or your repository's own
  record. `espalier init` names the per-machine homes your `.gitignore`
  actually ignores, and the session resume report says `no blueprint chain on
  this machine` rather than a fresh start, and names a blueprint engine that
  fails instead of reading it as an empty chain.
- **A review round that lost lanes is recorded as partial.** The finding
  ledger (`cc/finding_ledger.jsonl`) records each round's run counts and
  whether it was complete; the three review workflows pass them, the layered
  review records a round that found nothing, and the convergence critic
  reads the trend without the partial rounds, counting what it left out.
  Rows written before this release read as counts unknown.
