### Fixed

- **On Windows, a ledger filing and a plan reset no longer fail because another
  program has the file open.** Windows refuses to move a file over one a reader
  holds, and the ledger verbs' probe-roster write and the execution plan's
  demotion moved once and gave up, leaving a filing half-done or a plan still
  active. They now wait the reader out for up to about a second, as the
  harness's other writers already did. A kept, older `tools/cc/_paths.py`
  leaves them moving once, as before.
