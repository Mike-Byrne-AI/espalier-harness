### Fixed

- **`init` inside a virtualenv no longer wires a name that runs a too-old Python
  outside it.** In an activated 3.11 virtualenv whose `python` hid a 3.10
  further down PATH, `init` wired `python` and reported success. In the next
  shell started without the virtualenv (another terminal, an IDE, the desktop
  app), every hook found the 3.10 and refused every call. A name now counts as
  host-wide only when what it resolves to outside the virtualenv is a Python
  3.11 or newer that starts, or one that did not answer in time. Where a
  too-old Python is there, `init` (and `upgrade`, `merge-settings` and `fuse`)
  refuses before it writes any file. It names that Python and the virtualenv,
  and says the newer Python goes on PATH outside the virtualenv. Inside the
  virtualenv, `init --rewire-interpreter` no longer rewrites a wired `python3`
  to the virtualenv's `python`.
- **`doctor` names a wired name that runs a Python only inside a virtualenv**,
  when what it finds outside is a too-old Python or no Python at all (a
  Microsoft Store alias). `init` with nothing else on PATH still wires such a
  name, as it already did for a name with nothing outside the virtualenv.
