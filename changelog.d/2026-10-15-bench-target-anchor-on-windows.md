### Fixed

- **The end-to-end bench and the release-archive probe judge a path the same
  way on Windows and POSIX.** The bench's scenario loader, its work-dir check
  and the probe's pytest-argument check asked the host's `Path.is_absolute()`
  alone. On Windows that is False for a rooted path with no drive, so a
  scenario's `no_repeat_of: /etc/hosts` loaded and named `C:\etc\hosts`, and
  the bench's own outside-the-work-dir test was red on every Windows
  portability leg; on POSIX a drive or share path passed, and a climb in the
  middle (`tests/../../x.py`) passed everywhere. Each now asks one judge that
  reads the path as Windows does (every root, drive and share, both
  separators) and refuses an anchor or a `..` part anywhere. The probe judges
  a node id by its path, the part before `::`, refuses an `@file` argument
  whose contents pytest would read unseen, and names the `--opt=value` form
  for an option's value. A test holds the two copies of the judge to one
  verdict, since the two trees do not import each other.
