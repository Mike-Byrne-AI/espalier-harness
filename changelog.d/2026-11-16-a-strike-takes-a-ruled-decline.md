### Added

- **`tools/cc/ledger_row.py strike --declined <ruling id>` closes a row a
  ruling declined while its defect stands** (not work, a duplicate of a live
  row, a declared limit). The row's probe is driven in this checkout; one
  that no longer prints its open value is refused, since that close is a fix
  (strike it without `--declined`). The struck row records the ruling and
  the probe's reading ahead of the closing text, and the strike retires the
  probe itself. Until now a ruled close meant removing the open probe by
  hand and striking, and the struck row read as an ordinary strike.

### Changed

- **A strike refuses a probe changed by hand.** Where the base (the
  merge-base with the default branch, or `--base`) holds a probe for the row,
  its file under `task-packs/probes.d/` or its roster entry, and this tree
  holds no entry for it, or one whose command was emptied, the strike
  refuses and says how to restore it. `--no-base` does not skip this read. A
  row with no probe on either side strikes as before. A plain strike whose
  closing text opens with the decline's stamp is refused too.
