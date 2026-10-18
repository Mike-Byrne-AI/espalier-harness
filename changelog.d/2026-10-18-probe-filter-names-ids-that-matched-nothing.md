### Fixed

- **A probe-checker run asked for several ids now refuses when any of them
  matched no probe, and says which and why** (DEF-887). Before,
  `tools/cc/check_ledger_probes.py --id` refused only when no id matched. One
  real id plus a misspelling printed the full match's report and exited 0 in
  human, `--strikes` and `--json` mode, and nothing named the miss. A
  maintainer confirming a multi-id row's pins in one call read a green covering
  one id as a check of both.
  - **Now:** after the filter, the ids asked for are compared with the ids
    matched. On any miss the run refuses with exit 1, before any probe runs, in
    every mode. It prints the miss count, every matched id, and each miss on its
    own line. Each miss is quoted, so a stray space or an empty id shows, and
    gets one of three labels:
    - struck: its probe was retired at the strike, so drop it from the batch;
    - a live row with no roster entry;
    - in no ledger row: check the spelling.
  - **Unchanged:** a full match reports as before. When no id matches, the
    refusal keeps its text. The stale-claim count still covers only the ids the
    run drives.
  - **Help and usage:** both say the run refuses on an id with no roster
    entry. An entry that declares no oracle still matches, and reports
    NO_ORACLE.
