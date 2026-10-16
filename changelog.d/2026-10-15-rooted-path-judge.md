### Fixed

- **On Windows, a Bash `/tmp` is read where Git for Windows mounts it.** The
  Bash tool's `/tmp` is the user's temp directory, and the hooks read it as
  the drive root's `tmp`. After `cd /tmp`, a recursive delete of a clone kept
  there, by its name, passed with no nudge, while the same delete typed as
  `/tmp/<name>` drew it; from another directory, `cd /tmp/<checkout>` then a
  write below that checkout's `tools/cc` passed and a delete of `.` drew only
  the clearable nudge. Both delete spellings are now judged at every place
  the shell may mean, the drive root's `tmp` and the temp directory, so a
  clone at either keeps the nudge, and the directory chain places `cd /tmp`
  at the temp directory for the walls while keeping the drive root's reading
  beside it (Git Bash reads a backslash-led `\tmp` as the drive root's).
  PowerShell keeps reading `/tmp` as the current drive's `tmp`. The hooks see
  only their own environment's `TEMP`, so a harness that hands them a `TEMP`
  other than the session's is still read wrong.
- **The plan gate exempts a file outside the checkout in every spelling on
  Windows.** A rooted path with no drive (`/tmp/scratch.py`, `/etc/x.py`) was
  refused for want of a plan, while its drive and Git Bash drive spellings
  passed.
