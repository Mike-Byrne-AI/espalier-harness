### Fixed

- **The banner says when a seat's box lock is not the box's.** Once
  `ESPALIER_BOX_LOCK` was set, the box-lock note said nothing, whatever the
  path, and the seat launcher keeps a path the shell already set, so a seat
  still on a private lock path took no slot from the box's file and its tiers
  ran beside the other seats' with no word. On a named clone whose tree
  carries the suite's lock plugin, a set path other than the launcher's
  default now reads `box lock: this seat locks <path>, not the box's
  <default>` on the line the off-note rides. The paths are compared as the
  plugin compares them (case and separators as the host reads them, relative
  paths made absolute, no `~` expansion), and the launcher's old
  temp-directory default counts as the box's, since the plugin locks the
  home default in its place. A seat that meant its own path still reads the
  line; it blocks nothing.
