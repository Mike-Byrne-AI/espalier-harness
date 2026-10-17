### Fixed

- **`doctor`'s hook start check no longer takes minutes on a slow machine,
  and no longer blames hooks for it.** The check imports every wired hook in
  one child process. When that child ran out of time, it re-checked every
  hook in a child of its own: with the twelve standard hooks that was up to
  13 children and over four minutes, and on a slow machine each of those ran
  out too, so every hook was reported as unable to start.

  Now:
  - The check runs at most three child processes of 20 seconds each: about a
    minute at worst, a little more on Windows, where a stopped child can take
    up to 2 seconds to end.
  - When a child stops on a hook, it re-checks that hook alone, then the hooks
    after it together.
  - A child that ends at a hook's import was ended by that hook: that hook is
    named at once.
  - A child that never starts at all is read as a slow machine, so no hook
    is judged on it.
  - Hooks it did not reach are a warning that says why, with a next step, not
    a failure.

  A hook that hangs on its own is still reported by name as unable to start.
  On a healthy tree the check takes the same time as before.
