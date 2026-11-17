### Changed

- **Every audit record type a hook writes now sits in one declared family.**
  The governance audit log's readers each select by family: `/status --log`
  shows the block tiers and counts the maintenance bypasses and the
  voice-only records on lines of their own, and SessionStart names the
  voice-only records written since the previous start. Nothing checked that a
  type a hook writes belongs to any family, so a new record with no other
  channel, written under a name outside the voice-only family, would have
  reached neither reader. The harness's own tests now read every type the
  hooks can hand the audit writer, through each wrapper and composed name,
  and fail on a type in no family or in two. The records that already speak
  where they happen (the SessionStart warnings, the PostToolUse notices told
  to Claude, the handoff hold the prompt router names) are declared as
  channelled advisories, and `action_justification_missing` as the one type
  whose only voice is stderr, by design. No record, reader or channel
  changes. The hooks guide's audit-log section names the two new families.
