### Fixed

- **The interpreter-floor test of doctor's hand-edit sentence reads the
  report, not its JSON text (self-host).** It looked for the virtualenv's
  path, as Python prints it, in `espalier doctor`'s stdout, which is the JSON
  report: there each backslash of a Windows path is doubled and a non-ASCII
  letter is a `\u` escape, so the test failed on Windows while doctor's
  sentence was right. It now searches the strings the parsed report holds.
  Doctor is unchanged.
