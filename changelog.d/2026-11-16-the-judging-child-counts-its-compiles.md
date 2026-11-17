### Fixed

- **A loaded machine's time-budget refusal of an ordinary command asks for
  the re-issue, not a split, where start-up spent the time.** The guard's
  judging child marks when it begins judging, and the patterns a command
  reads compile on their first use, after that mark. So a deadline that
  landed in those compiles read as judging, and the refusal asked to split
  a command like `ls -la` into shorter ones, each of which pays the same
  start-up and the same compiles in its own process. The refusal now asks
  for the re-issue where start-up took at least judging's share of the
  bound, no speed-bump checkpoint had spent its one-shot nudge, and the call
  carries no command or one under 1,500 characters, at both the child's
  budget and the hook's deadline. Under that gate no measured command's
  length adds what a split would save: on a Windows box it sits under every
  crossing measured for a Bash delete list, a Bash `git add` and a
  PowerShell `Remove-Item` list, counting the compiles and the per-command
  cost a split repeats. A longer command keeps the split, as before. Where a
  checkpoint had spent its
  one-shot, the split stays too, since that nudge is keyed on the command
  and the identical re-issue would pass it unseen. The child says a spend on
  its error stream just before the spend, watching from the moment the
  speed-bump module loads, and its own refusal closes the spends before it
  reads its mark. Every refusal stays a refusal, and a call answered in time
  pays nothing new: the hook reads the command's length only at its
  deadline. The refusal's record carries the readings as `spent` and
  `short`.
