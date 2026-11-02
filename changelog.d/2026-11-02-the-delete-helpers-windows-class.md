### Fixed

- **The release smoke removes a `build/` directory it could not enter.**
  `scripts/wheel_smoke.py`'s stdlib delete helper answered a directory with
  no read bit by retrying the refused call bare, and `os.open` without its
  flags raised `TypeError`, so the smoke stopped and the tree stayed (a bare
  `os.scandir` instead listed nothing and the directory refused its removal).
  It now gives that directory its owner bits back and walks it again, once, as
  the engine's helper does; the two are driven alike over both of `rmtree`'s
  walks, and the parity tree gains a directory with no bits at all.

### Added

- **`portability.yml` takes a `python` input on a dispatched run** (3.12, the
  push and pull-request cells' own, or 3.13 or 3.14), so an arm only a newer
  interpreter takes, such as `os.chmod`'s `follow_symlinks=False` on Windows
  from 3.13, runs on a Windows host without a second cell on every pull
  request.
- **The suite contract refuses an `os.chmod` fake that cannot take
  `follow_symlinks`.** The delete helper passes the keyword on macOS and on
  Windows from 3.13, so a fake taking only the path and the mode passed on
  the Linux cells and raised `TypeError` on those hosts; a fake now takes
  `**kwargs` or names the keyword.
