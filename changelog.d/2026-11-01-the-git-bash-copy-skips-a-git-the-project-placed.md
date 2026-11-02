### Fixed

- **`espalier doctor` on Windows no longer counts a Git Bash that Claude Code
  will not use.** Claude Code skips a `git` that sits in the folder it was
  launched from, or below it under `node_modules` or a virtual-environment
  folder such as `.venv` or `env`, when it looks for Git Bash. Doctor's copy
  of that lookup asked every `git` on PATH, so on a host whose only Git sat
  inside the project it found a bash Claude Code passes over and said nothing
  about a statusLine an older `init` wrote bare, which Claude Code then runs
  under PowerShell and shows blank. Doctor now skips such a `git` as Claude
  Code does (judged against the repository root, by the rule read off the
  installed Claude Code binary), names the bare line, and its note says the
  `git` this repository placed is one Claude Code skips. (`DEF-3021`)
