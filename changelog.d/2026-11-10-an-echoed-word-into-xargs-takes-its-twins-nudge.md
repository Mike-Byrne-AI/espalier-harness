### Fixed

- **A word echoed into `xargs rm -rf` now draws the same speed bump as the
  remove it feeds.** `echo "$D" | xargs rm -rf` removes what `rm -rf "$D"`
  removes, but the guard read it as a remove with no operand and let it
  through without a prompt, at the top level, in a chain, an `if` or a loop
  body. Each such pipe is now judged as its direct twin: a variable or a
  source directory draws the confirm-and-re-issue prompt, a build-output
  word or a temp directory stays silent. A stage between the `echo` and
  `xargs`, the pipe split across a line, and an echo of more than four
  words or a word past 80 characters are still not read.
