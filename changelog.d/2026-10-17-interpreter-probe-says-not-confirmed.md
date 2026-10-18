### Fixed

- **SessionStart no longer tells you a working Python is too old when your
  machine is busy.** On a host loaded enough that an interpreter's `--version`
  missed its 2 s, the hook-side check read the interpreter running the hooks
  as below Python 3.10 and told you to install one you have. The interpreter
  running the hooks is now read directly, with no probe; any other wired
  interpreter whose probe never answers is named with its version "not
  confirmed" (a hang there still fails its hooks open, and the line says so),
  and the host line shows `?` for it, not `no`. On Windows a link of a
  virtualenv's `python.exe` in another folder is checked as the separate
  interpreter it is, by `doctor` too; elsewhere a symlink of the running
  Python, such as Homebrew's `python3`, is read as that Python.
