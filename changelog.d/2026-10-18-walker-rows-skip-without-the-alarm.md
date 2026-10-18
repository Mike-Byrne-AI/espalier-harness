### Fixed

- **On Windows, twelve rows of the ReDoS file (tests/test_redos.py) skip
  instead of failing.** The walker row's fix of earlier today (DEF-5023) put
  its warm call under the alarm. Twelve rows judge the walker on a simulated
  clock, and each still made that one real call through the walker's timer.
  On a host with no `SIGALRM` the timer raised `AttributeError` there. Every
  pull request whose Windows portability leg ran since read "12 failed".
  - **Now:** both timers that arm the alarm without a guard of their own,
    the walker's and the PowerShell body arm's, skip the test that reached
    them where the signal does not exist. That is the guard the file's 29
    other arming functions already carry. Each skip's reason names its timer.
  - **Driven on the Air**, with the signal removed before pytest loads: the
    file alone read the same twelve failures as the Windows leg before the
    fix, and 0 failed after it, with 12 more skipped. The Windows leg's
    serial step should read about 869 skipped where it read 857. Run
    normally, the twelve rows still run and pass.
  - **A new row takes the alarm away on every host and expects both timers to
    skip.** A pull request that drops either guard changes this file, so its
    own tier runs the row and it reds there, not only on the Windows leg 80
    minutes in. A third arming function elsewhere is not
    covered; DEF-5024 files that gate.
  - **The cost:** the twelve rows skip on Windows, where they ran before the
    warm call went under the alarm. They test arithmetic that does not
    depend on the host, and their docstrings now say they skip.
