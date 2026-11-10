### Fixed

- **`espalier --help` prints its links and flags whole.** argparse's default
  formatter wraps at hyphens and cuts long words, so in a 60- to 120-column
  terminal the Quickstart and Sharp-edges links in the top-level help ended a
  line at `espalier-` (clicking one opened a 404, or another user's GitHub
  profile), and a subcommand's help could split a flag such as
  `--add-gitignore` at its hyphen. Every `espalier` help now wraps at spaces
  alone; a word longer than the line runs past it instead of being cut.
