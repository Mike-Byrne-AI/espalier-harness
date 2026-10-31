### Fixed

- **The board's red line, the dispatcher's brief and the inbox body read the
  dispatcher's fix-forward ruling.** After the dispatcher ruled a red base a
  fix-forward (the ack opening `gridlock: fix forward run <id>` with `--lane`
  naming the fix lane, which `ship.py open --base-red-ruled <ack id>` lands
  on), `/inbox board` still printed `Revert first: git switch -c revert/...`
  under the one suspect, the dispatcher's own brief said `revert first on a
  red main` and nothing else, and the inbox body ended its base-branch bullet
  with `Revert first, diagnose second.`, so a seat reading the board after the
  ruling reverted the lane the ruling found blameless. The ruling now has one
  reader, in `tools/cc/mail.py` (`fix_forward_rulings` by run for the board,
  `fix_forward_ruling` by ack id for the driver, which delegates to it): the
  board's red line prints `ruled a fix-forward by <ack id> for <lane> (...):
  land the fix with ship.py open --base-red-ruled <ack id> on that lane
  (handoff takes the same flag), and revert nothing` in place of the
  revert and of the suspects' advice, says when no ruling could be looked for
  (the mail unread, the dispatcher setting unusable) beside the default, says
  when it was read from the refs as last fetched, keeps the disarm command for
  every armed lane but the fix lane (the ruling is for its lane alone), names
  the earlier rulings on the run beside the newest, and, where a newer red run
  supersedes the ruled one, prints the suspects with the older run's ruling
  beside them so the merge it found blameless is not reverted; the JSON
  carries it all under `post_merge`. The brief's red duty names the ruling
  beside the revert, which stays the default; the inbox body says what rules
  and what rules nothing; `ship.py open` on a `revert/` lane notes when the
  base's red run was ruled a fix-forward, since that revert undoes a merge the
  ruling found blameless. The driver's red-conclusion set now reads from
  `tools/cc/_post_merge.py` like its four siblings. (`DEF-5036`)
