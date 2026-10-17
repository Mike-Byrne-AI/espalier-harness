### Fixed

- **A plain `init .` keeps the settings profile the install was made
  with.** Re-running `espalier init .` without `--profile`, the repair the
  troubleshooting guide names, used to record the default `workflow` profile
  over a `minimal` or `full` install. `upgrade` and `doctor` then listed the
  workflow profile's allow rules, `Write` among them, as missing, with an
  append that would change the file's posture.
  - With no `--profile` and no `default_profile` in `espalier.toml`, a re-run
    over an install now keeps the profile it recorded, and the summary says
    so.
  - The record is read only beside an install (a non-empty
    `.claude/settings.json`). A fresh clone of a tree that committed its
    record takes the default, not the recording operator's profile.
  - A profile only the flag can select (`self-host`) is never taken from
    the record, and the summary names the flag that keeps it.
  - `upgrade --execute` now renders the installed profile, where it used to
    render the default's file beside a minimal install.
