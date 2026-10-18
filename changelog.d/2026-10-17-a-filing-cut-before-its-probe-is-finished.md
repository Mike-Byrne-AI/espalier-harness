### Fixed

- **A ledger filing cut off between its row and its probe is finished by
  running the same command again.** `tools/cc/ledger_row.py file` writes a
  row before its probe, so one interrupted in between (a full disk, a killed
  process) left a live row with no probe that no verb could finish: `file`
  refused the row as a duplicate, `repin` found no probe, and the probe
  runner's note led to a hand edit of the roster. Run again with the same
  arguments, `file` now finds its own row with no probe and writes only the
  probe, in both ways of keeping the ledger, and a filing with its id left
  out finds the id it already minted instead of filing the row twice. A row
  that differs from the one the arguments would write is refused by name and
  never overwritten.
