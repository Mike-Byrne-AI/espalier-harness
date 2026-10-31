### Fixed

- **The box lock's tests no longer red on a slow runner or under a Windows
  venv.** Two defects in `tests/test_box_lock.py` made its cases red against a
  lock that works.
  - **Fixed sleeps.** Five cases spawned a waiter behind a holder, slept 0.8
    to 1.0 s, and released the holder. A waiter still importing pytest passes
    the same check, so on a slow runner the holder went first and the waiter
    never printed its waiting line; #354's Windows portability leg red on
    exactly that. Each waiter's stderr is now read on a thread, and the test
    releases the holder at the waiter's first `box lock: waiting on` line.
    Every waiter's controller now sits in the scratch conftest until the lock
    is free, for 3 s at most. A margin put back at any site frees the lock
    first, so that case reds on any box. (`DEF-2027`)
  - **Redirector pids.** Three cases compared a spawned run's `Popen` pid with
    the pid the run records. Under a Windows venv, `python.exe` is a
    redirector that starts the interpreter as its own child, so the two never
    matched. These were the three red names the Windows box's full tier had
    carried as baseline; CI's interpreters are not venvs and passed them. Each
    run now writes its own pid for the test to read. (`DEF-2028`)
