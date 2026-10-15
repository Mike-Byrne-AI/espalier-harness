### Fixed

- **The edit-time sync advisories no longer go silent after five fires a
  session.** Root `CLAUDE.md` promises a PostToolUse advisory that names the
  right sync for every mirror row, but the mirror rows shared the recall
  engine's five-fire session budget with every other advisory, so a few hook
  edits spent it and the rest of the session heard nothing, even on an edit to
  a generated mirror that the next sync would discard. On the Windows box's
  logs 706 of 849 of their fires (83%) had been suppressed. Each of the seven
  sync advisories (some cover two mirror rows) now has two sides that leave the
  shared budget: the source side's "run the sync" reminder and the generated
  side's warning that the edit will be discarded, each said once a session, so a
  reminder on the source never spends the warning a later edit to the mirror
  needs. An edit to the vendored `espalier/_vendor/cc/` copy still gets no
  warning, as before.
- **When one edit trips more advisories than fit, priority alone decides
  which are shown.** An advisory exempt from the session budget used to jump
  ahead of every other one in the two-per-edit slice; it now takes its place
  by priority, so a correctness nudge (a loosened test, a raw marker substring
  test) is never displaced by a sync reminder, and an advisory that waits is
  said on a later edit. An advisory the session budget has already silenced no
  longer holds a slot it says nothing in, so the recall log now records it as
  capped by the session budget where it used to record it as waiting for a
  slot: counts of the two in that log are not comparable across this change.
  The rules are defined in code only, so no adopter configuration changes
  meaning.
