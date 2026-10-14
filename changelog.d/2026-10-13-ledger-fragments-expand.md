### Added

- **The forward ledger's rows and probes can live in one file each.** Where
  `espalier.toml` sets `ledger_fragments = true`, `tools/cc/ledger_row.py file`
  writes a new row as `task-packs/ledger.d/<id>.md` (its class, its member row
  and its Appendix B index lines) and its probe as
  `task-packs/probes.d/<id>.json`, and `strike` and `repin` edit a row where it
  lives. Two lanes filing into one class, or striking two neighbouring rows,
  then change different files and merge clean, where they used to meet on
  neighbouring lines of the ledger and the roster's tail (driven on the real
  verbs: two filings after one anchor conflicted on the member row, its index
  row and the roster). Off by default: every other tree keeps one ledger file
  and one roster, written as before.
- **Every reader takes the ledger's view.** The view is the ledger file with
  the row files placed where the verbs used to write them, built on each read
  and never written back; `python tools/cc/_record_fragments.py ledger` prints
  it. The generator's check, the probe runner, the record merge, the board, the
  landing check, the trend and the census scripts read it, and a row file the
  view cannot place is reported, never dropped. `python
  tools/cc/_record_fragments.py probes` prints the roster the same way: the
  file's entries, then the probe files.

### Changed

- **The record-file lists know the two directories.** The merge gate scans a
  probe file's JSON for a leftover conflict marker, the record merge refuses a
  conflict on one row file by name (two writers on one id), both `.gitignore`
  blocks re-include the directories (`upgrade` delivers the adopter's), and the
  files ship with the ledger.
- **On a tree that keeps rows as files, a ledger verb refuses only on what it
  would make worse.** A problem the tree already carried about another row (a
  stray file beside the rows, a second probe for one id) is printed as a note
  and the filing, strike or re-pin goes ahead; one about a row the verb
  touches, or one its own write would add, still refuses. `--check`, the
  ledger's CI gate and the record merge hold the tree to every problem, the
  roster's own included. A tree that has not opted in refuses on every
  problem, as before. What an operating system or an editor leaves in the two
  directories (`.DS_Store`, a swap file, a `~` backup) is never read as a row.
- **A strike retires its probe before it writes the struck row,** so one that
  dies part-way leaves a live row with no probe, which running the strike
  again finishes.
