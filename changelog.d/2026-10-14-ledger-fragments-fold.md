### Changed

- **The record merge no longer runs a settle step after every merge.** The
  step dropped a `_count` that a merge brought back into
  `task-packs/LEDGER_PROBES.json`, for lanes branched before the roster stopped
  storing a total. No ledger verb has written the key since then, so the step,
  its commit (or amend) after a clean merge and its undo are gone. A conflicted
  roster still drops the key when it is merged by shape. A clean merge that
  brings the key back leaves it in the file, where nothing reads it (every
  reader counts the list), and the next ledger verb's write drops it.
