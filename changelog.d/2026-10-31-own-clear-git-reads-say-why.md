### Fixed

- **The own-clear says why a git read failed.** The mod's `git()` helper kept
  stdout alone, so a held clear and a re-prime read `HEAD could not be read`
  or `git status could not be read (no output)` with nothing after it (win-2's
  re-prime, 2026-10-31, while HEAD equalled the marker's head; that read's
  cause is still unknown), and a checkout top git could not read fell back to
  the session's folder silently. `tools/cc/mods/own-clear/hooks/register.ts`
  carries why each read failed -- `exit <code>` and git's stderr after it (one
  line, its last 200 characters, where `fatal:` sits), or the engine's
  rejection when git could not start or outran its 10 s timeout -- onto the
  status line, the re-prime's brief and the mod's log. The kit gains a case
  per read, each handing it a failing value and reading the reason back;
  `tests/test_own_clear.py` pins by text that the helper reads stderr and that
  each git read's reason is read in the function that made it, since no CI
  cell installs `claude`.
