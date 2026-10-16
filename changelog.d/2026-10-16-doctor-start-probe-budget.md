### Fixed

- **`doctor`'s hook start check no longer takes minutes on a slow machine,
  and no longer blames hooks for it.** The check imports every wired hook in
  one child process. When that child ran out of time, it re-checked every
  hook in a child of its own: with the twelve standard hooks that was up to
  13 children and over four minutes, and on a slow machine each of those ran
  out too, so every hook was reported as unable to start.

  Now:
  - The check has one time budget of 60 seconds in all.
  - It re-checks only the hook the first child stopped on, then the hooks
    after it together.
  - A child that never starts at all is read as a slow machine, so no hook
    is judged on it.
  - Hooks it did not reach are a warning that says the machine was slow,
    not a failure.

  A hook that hangs on its own is still reported by name as unable to start.
  On a healthy tree the check takes the same time as before.
