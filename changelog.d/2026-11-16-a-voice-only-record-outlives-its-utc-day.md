### Fixed

- **A record that is a hook's only voice reaches you past its UTC day.** A
  fault a guard allowed through (the Stop gate's test run killed at its
  budget, a settings scan skipped) is written once a session to the audit log
  and said to Claude Code's debug log, which nobody reads; a kill switch in
  managed policy settings, which ConfigChange cannot block, is written the
  same way. Only `/status --log` read them, and only from today's UTC log, so
  they were gone from view once the date turned, and the policy record was
  never shown at all. The next session's banner now names, in its Warnings
  block, the records of this family written since the previous start, by type
  and count, whatever day they fall on (the read is bounded at seven UTC days
  and 4 MB, and says when it stopped). `/status --log` reads today's and
  yesterday's logs, labels the window (`since <date> 00:00Z` where it said
  `today`), and counts the family, the policy record included, on a
  `voice-only` line in place of the `fail-open` one.
