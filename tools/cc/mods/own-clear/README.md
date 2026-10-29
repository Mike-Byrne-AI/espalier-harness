# The own-clear mod

A Claude Code mod (a plugin of function hooks, 2.1.287+) that ends a seat's
window the way the handoff means it to: once `ship.py handoff` has landed, the
window runs the real `/clear` on its own, refuses the compaction that would
write the handoff's summary a second time, and re-primes the cleared window
with the seat brief. A seat launched by `tools/cc/seat.py launch` loads it
through `--plugin-dir` and exports `ESPALIER_OWN_CLEAR=1` to the session;
nothing else loads it, and a handoff in any other window arms nothing and
says the window needs a `/clear` by hand.

## The three pieces

1. **The marker.** The handoff's last act (`tools/cc/ship.py::arm_own_clear_here`)
   writes `.espalier-state/own_clear.json`: `state` (`armed`), `session_id`
   (the id Claude Code exports to its tool shells as `CLAUDE_CODE_SESSION_ID`,
   which tracks the session across a clear), `head`, `seat`, `role`, `brief`
   (`seat.py::reprime_text`: the role brief with its loop line replaced, since
   the interval loop survives a `/clear`) and `written_at`. Only in a window
   that loaded the mod; with no session id in the environment nothing is
   armed; and an arm that fails never fails the handoff whose push landed.
2. **The clear.** At the end of the main loop's next turn (`turn.complete`,
   reason `answer`), when the marker names this session, HEAD is still the
   marker's, `git status --porcelain --untracked-files=no` is empty and
   `cc/execution_plan.json` is not `in_progress`, the mod runs
   `$.command.run({ command: 'clear', args: '' })`, not awaited, once per
   session. Anything in flight keeps the marker armed and names the wait on
   the status line; a clear the engine refuses says so there and is tried
   again at the next turn's end.
3. **The re-prime.** On the clear's SessionStart (`classic.SessionStart`,
   `source: 'clear'`) the mod reads the marker before handing the event on (the
   project's settings hooks run beneath a mod's), and only when the marker
   names the session this process was in before the clear rewrites it as
   `consumed` with the new session id and submits the brief with `asUser`. A
   marker armed by another window, or by a session this process never saw, is
   marked `stale` and re-primes nothing. A marker with no brief gets one
   generic line; a marker that cannot be rewritten still re-primes.

While the marker is armed for this session and the clear can run (or is under
way), `session.compact` on the main loop answers `{ skip }`; while the clear
waits, the compaction runs, so a held window never fills.

## Measured (2026-10-26, Claude Code 2.1.310, the Air)

`reports/own-clear-probe-2026-10-26/` on the Air holds the probes and logs. The
clear: Stop, SessionEnd `reason=clear`, SessionStart `source=clear` with a new
session id, the window alive, in `-p` and interactive. The re-prime: the
prompt lands as a UserPromptSubmit in the new session 70 ms after its start;
clear and re-prime together took 1.4 s. In `claude -p` the process exits right
after the clear, so the re-prime is interactive-only. A `/compact` while a
`session.compact` hook skips reads `Not compacted` and the classic PreCompact
never fires. `CLAUDE_CODE_SESSION_ID` in a tool shell changes with the session
at a clear. The Windows seats are unmeasured (their `claude` is a cmd shim).

## Environment

- `ESPALIER_OWN_CLEAR`: `1` in a session `seat.py launch` started with the mod;
  the handoff's gate.
- `ESPALIER_OWN_CLEAR_ROOT`: the checkout the marker lives in, for a test or a
  drive; unset, `git rev-parse --show-toplevel` from the session's directory.
- `ESPALIER_OWN_CLEAR_LOG`: a file the mod appends one JSON line per event to;
  unset, nothing is written.

The launcher never passes the three into a session from its own environment.

## Checking it

```bash
claude plugin validate tools/cc/mods/own-clear      # the manifest and the module, as the engine reads them
claude plugin test tools/cc/mods/own-clear          # hooks/own-clear.test.ts against the engine
python bench/own_clear/drive.py                     # the real thing: a pty-driven session, the marker armed by ship.py
```

A Python contract test in the suite pins the two sides to each other (the
marker's path and states, the flag, the two variables). The engine writes
`.claude-plugin/types/` and a `tsconfig.json` beside a mod it loads (for the
editor); both are gitignored.
