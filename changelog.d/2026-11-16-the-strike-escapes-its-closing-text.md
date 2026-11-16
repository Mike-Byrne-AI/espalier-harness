### Fixed

- **A ledger verb keeps a row whole when its text quotes a pipeline.** A
  strike's closing text, a filing's or a repin's row text, every anchor and
  a new class's effort cell went into their ledger cells as typed, so a bare pipe in them (a quoted
  `ls | head`) split the row: the strike and the filing wrote a five-cell row
  and exited 0, and only the ledger's completeness test caught it, at the
  pull request. Each verb now escapes a bare pipe in those texts the way the
  ledger escapes one (`\|`) before it writes the row. A code span keeps its
  backticks, and a pipe already escaped by hand stays escaped once.
