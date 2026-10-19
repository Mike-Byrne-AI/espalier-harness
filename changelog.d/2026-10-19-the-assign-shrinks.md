### Added

- **An assign has a shape, and the mail driver notes a text outside it.** The
  dispatcher's assign names the job, why now, what it waits for, the operator's
  constraints and an edge with its citation, under 900 characters, and never the
  tier or the reviewers a tier script prints from the diff
  (`memory/parallel-work-protocol.md`, *What an assign says*). `mail.py send
  --type assign` prints a note on stderr, never a refusal, past 900 characters
  (`ASSIGN_SHAPE_CHARS`), and on Espalier's own source repository on a tier or
  reviewer phrase too (`ASSIGN_SHAPE_WORDS`, the dispatcher's `tier:` and
  `review:` forms included, a hyphen read as a space; `assign_shape_notes`), on
  `--dry-run` alike; the deployed driver notes the length only, since an
  adopter tree has no tier script. The self-host dispatcher brief carries the
  shape clause; the adopter brief does not.

### Changed

- **A seat proceeds on its own read.** On a fork the assign does not settle, a
  seat sends its request with its Task 0 recommendation and proceeds after the
  dispatcher's tick interval (15 minutes, pinned to the loop's own number by a
  test) with no answer; it stops only for what the assign authority reserves for
  the operator, a platform stop, an unresolved refusal or a conflict outside its
  files; a red it cannot fix in two attempts shelves the lane (one note beginning
  `shelved:`) and the seat takes its next queued job; a redirect after the fact
  is an ack beginning `redirect:`. The queue depth is two in both places the
  protocol states it. The worker tick template is unchanged until the operator
  pastes its new sentence (the protocol's "The seat's side of it").
