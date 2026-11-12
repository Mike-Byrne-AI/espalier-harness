### Fixed

- **`init` inside a virtualenv no longer wires a name that runs a too-old Python
  outside it.** In an activated 3.11 virtualenv whose `python` hid a 3.10 (or a
  Microsoft Store alias, which is no Python at all) further down PATH, `init`
  wired `python` and reported success. In the next shell started without the
  virtualenv (another terminal, an IDE, the desktop app), every hook found the
  3.10 and refused every call, or found the alias and failed open. A name now
  counts as host-wide only when what it resolves to outside the virtualenv is a
  Python 3.11 or newer that starts. Where a too-old Python is there, `init` (and
  `upgrade`, `merge-settings` and `fuse`) refuses before it writes any file,
  names that Python and the virtualenv, and says the newer Python goes on PATH
  outside the virtualenv. `doctor` names the wired name's outside interpreter,
  and `init --rewire-interpreter` run inside the virtualenv no longer rewrites a
  wired `python3` to the virtualenv's `python`.
