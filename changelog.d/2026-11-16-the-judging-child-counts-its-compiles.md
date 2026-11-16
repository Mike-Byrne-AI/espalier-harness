### Fixed

- **A loaded machine's time-budget refusal of an ordinary command asks for
  the re-issue, not a split, where start-up spent the time.** The guard's
  judging child marks when it begins judging, and the patterns a command
  reads compile on their first use, after that mark. So a deadline that
  landed in those compiles read as judging, and the refusal asked to split
  a command like `ls -la` into shorter ones, each of which pays the same
  start-up and the same compiles in its own process. The refusal now asks
  for the re-issue wherever start-up took more of the bound than judging
  and no speed-bump checkpoint had spent its one-shot nudge. Where one had,
  it keeps the split, since that nudge is keyed on the command and the
  identical re-issue would pass it unseen. The child says a spend on its
  error stream just before the spend, and its own refusal closes the
  spends as it reads them. Every refusal stays a refusal, and a call that
  fires no checkpoint pays nothing new. The refusal's record carries the
  reading as `spent`.
