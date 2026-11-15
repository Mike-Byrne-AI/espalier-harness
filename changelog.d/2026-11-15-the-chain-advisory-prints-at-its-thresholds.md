### Changed

- **The ledger's chain advisory now prints the chain when it fires.** Filing a
  row with `ledger_row.py file --sibling-of` used to print one recording-only
  line. Now, when the new row is a sibling of a sibling or a parent's third
  child, it prints the chain from child to root, each parent's children, the
  root's site family and the five layer questions. It still never refuses and
  never changes an exit code. The thresholds stay at depth 2 and fan-out 3.
  Their review, read over the first 20 filings carrying `--sibling-of`, found
  the advisory would have fired on 6 of them. The recording-only line returns
  if `CHAIN_ADVISORY_PRINTS` is turned off.
