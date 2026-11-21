### Fixed

- **The banner says when a seat's box lock is not the box's.** Once
  `ESPALIER_BOX_LOCK` was set, the box-lock note said nothing, whatever the
  path, and the seat launcher keeps a path the shell already set, so a seat
  still on a private lock path took no slot from the box's file and its tiers
  ran beside the other seats' with no word. On a named clone whose tree
  carries the suite's lock plugin, a set path other than the launcher's
  default now reads `box lock: this seat locks <path>, not the box's
  <default>` on the line the off-note rides, the path made absolute as the
  plugin opens it, so a `~/...` that no shell expanded cannot read as the
  box's file. The paths are compared as the plugin compares them (case and
  separators folded on Windows alone, no `~` expansion), and the launcher's old
  temp-directory default counts as the box's, since the plugin locks the
  home default in its place. A seat that meant its own path still reads the
  line; it blocks nothing.
- **The kill speed bump reads the lock the suite takes.** Its box-lock
  reading read `ESPALIER_BOX_LOCK` as set, so a seat whose shell still
  exported the launcher's old temp-directory default, which the suite's
  plugin moves to the home file, saw no holder there, and on Windows, where
  that reading is the only one, a kill of another seat's tier was not
  nudged. It now reads the variable's file and, where the path bears the
  lock's own name, the home file beside it, a holder counted once, so a
  victim whose plugin did not move the path is read too.
