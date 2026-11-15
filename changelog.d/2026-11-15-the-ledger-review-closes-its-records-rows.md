### Fixed

- **A command's Purpose in the generated CLAUDE.md table skips what the
  command index skips.** For a command with no frontmatter `description:`,
  the table took the body's opening paragraph and skipped only a leading
  heading, so a body opening with a blockquote, an HTML comment such as the
  managed marker, or a fenced code block showed that block as the Purpose,
  while `cc/COMMANDS.md` showed the prose after it. Both readers now skip
  the same blocks and stop on the same lines, and a test drives both over
  the same bodies. The table reads the packaged commands alone, and each of
  them carries a description, so no rendered row changes today; the
  fallback can no longer drift from the index the day one does not.
