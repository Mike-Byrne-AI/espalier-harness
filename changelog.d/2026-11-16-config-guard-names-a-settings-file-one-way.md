### Fixed

- **The settings guard's records name the file a change named, never the
  path the change carried.** A refusal over a kill switch beside a command or
  skill change recorded that markdown file's absolute path (the home
  directory included) next to a finding about `.claude/settings.json`, and
  the refusal of a change that unwires the gates recorded the payload's path
  as given. The guard now decides which settings file a change names by one
  rule, read once a change, and every record names that file by its label,
  or by a fixed word (`another-in-root-file`, `a-file-outside-the-root`) for
  any other file. A project or local settings file symlinked out of the
  repository is now read where the guard reads that file, so one it cannot
  parse is said once a session like any other, where before it wrote no
  record.
