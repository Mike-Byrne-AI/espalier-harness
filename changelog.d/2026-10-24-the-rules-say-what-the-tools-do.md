### Changed

- **The reflect link check reads a record surface's dead pointer as aging, not a
  gap.** Both reflect twins (`tools/cc/reflect_protocol.py`, the copy the
  PostToolUse hook runs, and `espalier/reflect_protocol.py`) report a broken link
  or anchor on an append-only record as kind `aging`, severity `low`, described
  as `Aging pointer on a record surface`, and `gap_count` no longer counts it
  (Core Rule 13: editing the pointer would falsify the record). The record set is
  `RESIDUE_EXEMPT_SURFACES` minus the hot index, `ESPALIER_MEMORY.md`, which is
  kept current at every handoff, so its dead link stays a high gap. The
  standalone report gains `aging_count` beside `gap_count`; the engine's render
  gains an `Aging:` line and an `[AGING]` group, derived from the findings
  (`ReflectPass` keeps its fields, so the blueprint projection carries the aging
  findings and not the count), and `espalier reflect-deep` still exits on gaps
  alone. The lighter scan behind `espalier reflect` and the doctor
  (`espalier/reflection.py`) reads the same set: a record's dead pointer leaves
  `broken_markdown_links` for a new `aging_pointers` list, so neither verb tells
  a seat to fix a record while the hook tells it to leave one alone. The set has
  one derivation per twin, `AGING_RECORD_SURFACES`, pinned equal across them.
  `reflect_trigger.py`'s clean test reads past aging findings: a pass whose only
  findings are aging injects nothing (its debug line says how many it read past),
  and on a pass with drift the advisory's count and names cover the drift alone.
  The reflect skill's report template gains an `AGING POINTERS` line.
- **The seat briefs name the handoff, and the mail cap has its reason.**
  `WORKER_BRIEF` and `DISPATCHER_BRIEF` gain one clause each before their last
  sentence, naming `/handoff` as what writes the seat's Session Log row and ships
  or parks it. `MAX_TEXT`'s comment in `tools/cc/mail.py` declares why the cap is
  2,000 (a message points at a lane, a row, a pack or a decision; the proof lives
  in the tree; a longer body is a message and notes) and the inbox command body
  points at it instead of restating the number. `memory/local-codename-arm.md`
  gains the rule that a tell moves by expand, then contract, and why the
  2026-10-18 move was left as a flag day.
