### Fixed

- **Moving or deleting a directory that holds harness files names them and
  offers neither the relaunch nor the relocate.** A directory such as
  `tools/` holding `tools/cc/`, or `.github/` holding the harness-guard
  workflow, was refused with the harness's text: relaunch in maintenance mode,
  or relocate it from your own terminal. Either takes the harness's files with
  your directory, and its hooks stop with them. The refusal now names the
  harness path inside and says to move your own files out one by one and leave
  the harness's in place. Where an entry in `espalier.toml` (`protected_paths`
  or `generated_paths`) covers the directory, it names that entry too and says
  to narrow it, from your own terminal, before moving your own files. This
  holds on Bash, PowerShell and MCP.

  What is refused is unchanged. A write, copy, link or permission change on
  such a directory touches no harness file and keeps your zone's own text. A
  harness path itself, or one inside it, keeps the harness text. An entry you
  wrote for a harness path itself (such as `tools/cc/`) no longer reads as a
  zone of yours holding the harness.
