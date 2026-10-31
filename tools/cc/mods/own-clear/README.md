# The own-clear mod

A Claude Code mod (a plugin of function hooks, 2.1.287+) that ends a seat's
window the way the handoff means it to: once `ship.py handoff` has run to its
end (its push landed, or refused by something the window is done with), the
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
   the interval loop survives a `/clear`), `landed` and `outcome` (how the
   handoff ended, DEF-4057: a push that landed, or a refusal the window is
   done with -- the base red and the lane whole here, or a step after a landed
   push -- whose text rides `outcome` while the lane to land first is appended
   to `brief`, so the next window lands it before any new job) and
   `written_at`. The handoff arms on every end it ran to; a refusal the
   window must fix first (a dirty tree, a lane behind its remote) arms
   nothing, and `python tools/cc/ship.py arm [--why ...]` arms by hand after a
   lane opened by hand. Only in a window that loaded the mod; with no session
   id in the environment nothing is armed; and an arm that fails never fails
   the handoff whose step has run.
2. **The clear.** At the end of the main loop's next turn (`turn.complete`,
   reason `answer`), when the marker names this session, HEAD is still the
   marker's, `git status --porcelain --untracked-files=no` is empty and
   `cc/execution_plan.json` is not `in_progress`, the mod writes
   `clear_asked_at` into the marker and runs
   `$.command.run({ command: 'clear', args: '' })`, not awaited. A clear
   asked while a prompt is already queued (a loop tick that fired as the turn
   ended) runs after that prompt's turn (measured 2026-10-30, below), and is
   never asked again while the session stands (with two prompts queued, a
   second ask would be a second clear over the window the first re-primes):
   every later turn's end in the same session names the queued clear on the
   status line, with what that turn left in flight, and a compaction is let
   through once two turns have passed, so a clear the engine lost never
   freezes the window; the operator's own `/clear` ends the wait. Anything in
   flight keeps the marker armed and names the wait on the status line; so
   does a git read that fails, with why: `exit <code>` and git's stderr
   after it (one line, its last 200 characters, where `fatal:` sits), or
   the engine's rejection when git could not start or outran its 10 s
   timeout; the re-prime's brief carries the same text (DEF-3019,
   2026-10-31: win-2's re-prime said `HEAD could not be read` while HEAD
   equalled the marker's, and nothing said why; that read's cause is still
   unknown, and the next such read names its own). A clear the engine
   refuses says so there and is tried again at the next turn's end. **Every outcome goes on the marker** (DEF-5031, 2026-10-30: the
   dispatcher window re-asked a refused clear 41 times over ten hours with the
   refusal on a status line nobody read and the log off): a rejected ask
   writes `clear_refused` (the engine's text), `clear_refusals` (a count) and
   `clear_refused_at`, the state staying `armed`; each later turn's end under a
   queued clear writes `turns_since_ask` and, once the engine has answered the
   ask with the session still standing, `clear_resolved_at`, so a clear taken
   and never run reads apart from a queued one and a refused one. The
   SessionStart banner's `Own-clear:` line (`tools/cc/hooks/session_start.py`)
   reads the record for every other session, and the prompt router
   (`tools/cc/hooks/task_router.py`) tells the window whose own asked clear was
   refused to say so in its reply.
3. **The re-prime.** On the clear's SessionStart (`classic.SessionStart`,
   `source: 'clear'`) the mod reads the marker, and what the old window left
   in flight against the marker's head, before handing the event on (the
   project's settings hooks run beneath a mod's: a sweep there would take the
   marker, and the checkout catch-up there moves a checkout whose lane merged
   onto the base, which read after the hand-on named itself as work left in
   the old window on every such re-prime, DEF-5028), and only when the marker
   is this process's own -- armed for the session it was last in, or for the
   session it asked to clear while that ask stands, or, with no last session
   known (a reload reset the module), carrying its own `clear_asked_at` --
   rewrites it as `consumed` with the new session id and submits the brief
   with `asUser`, what was left in flight named after it. A marker armed by
   another window, or by a session this process never saw, is marked `stale`
   with the two ids it compared (`previous_session_id`, `stale_because`) and
   re-primes nothing. A marker with no brief gets one generic line; a marker
   that cannot be rewritten still re-primes. Under a pending clear a turn's
   end, and a `session.start` should an engine raise one at a clear, move the
   last session only to the asked one (DEF-5032, 2026-10-30: a queued clear
   was dequeued 5 ms after the tick turn's end, while that turn's handler was
   still resolving the session id, so the handler took the new id, the
   SessionStart read its own marker as another window's and re-primed nothing);
   the clear's SessionStart clears the pending ask once the marker is consumed
   or stale.

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
at a clear. The Windows seats were unmeasured then (their `claude` is a cmd
shim); on win-2 (2.1.314, 2026-10-31) the mod's log names a clear's marker
consumed and its brief submitted, and the kit runs green there. The pty driver
(`bench/own_clear/drive.py`) stays POSIX-only.

**A queued prompt defers the clear by one turn (2026-10-30, 2.1.314, the
dispatcher seat).** The handoff armed the marker at 02:08:22Z; the board loop's
tick, due at 02:07, fired as the turn's Stop hook returned (02:08:32.069Z), its
prompt was dequeued at .073, and the mod's `/clear` was enqueued at .130 behind
it (the transcript's `queue-operation` rows). The engine dequeued the clear when
the tick's turn ended (02:10:19Z) and the marker was consumed at 02:10:24Z. The
clear was deferred, never lost, and a second ask at the tick turn's end would
have cleared the re-primed window; with two prompts queued ahead no turn count
tells a queued clear from a lost one. That is why the mod never asks again while
the session stands, names the queued clear on the status line instead, lets a
compaction through once two turns have passed, and records `clear_asked_at` in
the marker (read back by the banner's `Own-clear:` line, the prompt router, and
the mod's own reload arm, which takes a marker asked under a day ago as this
checkout's own when a reload has reset the module's memory).

## Environment

- `ESPALIER_OWN_CLEAR`: `1` in a session `seat.py launch` started with the mod;
  the handoff's gate.
- `ESPALIER_OWN_CLEAR_ROOT`: the checkout the marker lives in, for a test or a
  drive; unset, `git rev-parse --show-toplevel` from the session's directory
  (a read that fails falls back to that directory, git's reason on the log).
- `ESPALIER_OWN_CLEAR_LOG`: a file the mod appends one JSON line per event to,
  capped (past 256 KB the newest 500 rows are kept), its writes chained so two
  in flight at once drop nothing; unset, nothing is written and the marker is
  the one record. `seat.py launch` sets it for every session the mod rides
  (`.espalier-state/own_clear.log` under the seat's checkout, the default since
  DEF-5031); `--own-clear-log PATH` moves it (a relative path is resolved where
  it was typed) and `--no-own-clear-log` leaves it unset.

The launcher never passes the three into a session from its own environment;
the log is the one it sets on its own.

## Checking it

```bash
claude plugin validate tools/cc/mods/own-clear      # the manifest and the module, as the engine reads them
claude plugin test tools/cc/mods/own-clear          # hooks/own-clear.test.ts against the engine
python bench/own_clear/drive.py                     # the real thing: a pty-driven session, the marker armed by ship.py
```

A Python contract test in the suite pins the two sides to each other (the
marker's path and states, the flag, the two variables, the SessionStart
handler's two reads before the hand-on, every git read's reason read) and runs
the kit above wherever `claude` is on PATH, with the pass count derived from
the kit file, so a broken case reds the local tier; no CI cell installs
`claude`, so there the kit is the seat's run. The engine writes
`.claude-plugin/types/` and a `tsconfig.json` beside a mod it loads (for the
editor); both are gitignored. The types directory ignores itself (its own
`.gitignore` is a bare `*`), and the post-shell protected-file check prunes a
directory that does, so the type declarations the engine rewrites at a launch
report nothing; the `tsconfig.json` beside the mod is written once, at the
mod's first load in a checkout, and that one appearance reports once. The
root `.gitignore` also names a `.claude-plugin/test-tmp/`, which the kit did
not write on 2.1.314 (a run left nothing beside the mod); a directory that
appears there without a `.gitignore` of its own reports like any other file,
since a root `.gitignore` entry exempts nothing.

The engine hands an `fs.*` hook the path as it resolved it on the host: on
Windows the kit's `/scratch/...` arrives as `C:\scratch\...`. So the kit's
world holds its files in one store that keys every path one way (`Files`,
`key()`), and a case that keeps a path anywhere else reds on Windows alone
(`DEF-3016`: 27 of 32 cases did, on 2.1.311, 2.1.312 and 2.1.314 alike).
