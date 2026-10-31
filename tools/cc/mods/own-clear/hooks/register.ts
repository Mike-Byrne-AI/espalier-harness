import type { EngineInterface, Register } from 'claude-code'

// The own-clear (Espalier-Harness, 2026-10-26). A seat's session ends its work
// with the handoff, which writes the row and the summary and pushes the lane;
// what used to follow was the operator's /clear, or a compaction that wrote
// the summary a second time. This mod runs the real /clear itself and
// re-primes the window:
//
//   - the handoff's last act (tools/cc/ship.py::arm_own_clear_here) arms
//     .espalier-state/own_clear.json for the session id Claude Code exports to
//     its tool shells, with HEAD and the seat's re-prime brief, in a window
//     that loaded this mod (seat.py launch exports ESPALIER_OWN_CLEAR=1);
//   - at the end of the main loop's next turn, when that marker names this
//     session, HEAD is still the marker's, no tracked edit is in flight and no
//     plan is in progress, the mod runs $.command.run({ command: 'clear' })
//     (measured 2026-10-26 on 2.1.310: Stop, SessionEnd reason=clear,
//     SessionStart source=clear with a new session id, the window alive);
//     anything in flight keeps the marker armed and names the wait on the
//     status line; a clear the engine refuses says so there and on the marker
//     (the reason, when, a count: the record the banner's Own-clear: line
//     reads, DEF-5031) and is tried again at the next turn's end; a turn's
//     end under a pending clear never moves the session this process was last
//     in (DEF-5032: the queued clear flips the session under that handler);
//   - on that SessionStart (classic.SessionStart, source=clear) the mod reads
//     the marker, and what the old window left in flight against the marker's
//     head, BEFORE handing the event on (the project's settings hooks run
//     beneath it: a sweep there would take the marker, and the checkout
//     catch-up there moves a merged lane's checkout onto the base, which read
//     after the hand-on named itself as work left in the old window), and only
//     when the marker names the session this process was in before the clear
//     (a marker another window armed, or one this process never knew, is
//     marked stale and re-primes nothing) marks it consumed and submits the
//     brief as the first message of the new session, what was left in flight
//     named after it (measured: it lands 70 ms after the start);
//   - a compaction asked for while the marker is armed for this session AND
//     the clear can run (or is already under way) is refused ({ skip }): the
//     handoff already wrote the summary. While the clear waits, the compaction
//     runs, so a held window never fills.
//
// No settings hook, skill or command body can clear or compact; only a mod
// can. Loaded by `seat.py launch` through --plugin-dir. command.run and
// prompt.submit are never awaited inside a hook (the docs' own retry example
// does the same); the once-guard is keyed by the session id, never a flag.

const MARKER = '.espalier-state/own_clear.json'
const PLAN = 'cc/execution_plan.json'
// The log's bound: past LOG_BYTES the newest LOG_KEEP rows are kept (the
// launcher turns the log on by default since DEF-5031, so a long-lived window
// must not grow it without end).
const LOG_BYTES = 256 * 1024
const LOG_KEEP = 500
// Two variables, each named literally at its $.env.get (the engine lists what
// a module reads): ESPALIER_OWN_CLEAR_ROOT, the checkout the marker lives in
// when a test or a drive names one (else `git rev-parse --show-toplevel` from
// the session's working directory), and ESPALIER_OWN_CLEAR_LOG, a file the mod
// appends one JSON line per event to (docs/ENV_CATALOG.md); unset, nothing is
// written.
const GENERIC_BRIEF =
  'The previous session handed off and this window was cleared by the own-clear. Orient from the banner and ' +
  'read live state before you state it. A loop that was running survived the clear: start no second one.'
const FAILED_STATUS = 'own-clear: the clear was refused; type /clear, or it is tried again at the next turn'
const QUEUED_STATUS = "own-clear: the clear is queued behind the prompt that ran first; it runs at this turn's end"
const SKIP_REASON = "own-clear: the handoff wrote the summary; this window clears at the turn's end instead"

type Marker = {
  state?: string
  session_id?: string
  head?: string
  seat?: string | null
  role?: string | null
  brief?: string | null
  // How the handoff ended (tools/cc/ship.py, DEF-4057): read by nobody here,
  // kept whole through every rewrite; the brief carries what the next window does.
  landed?: boolean
  outcome?: string | null
  written_at?: string
  clear_asked_at?: string
  // The record the process does not keep (DEF-5031, DEF-5032): read by the
  // banner's Own-clear: line (tools/cc/hooks/session_start.py) and the prompt
  // router's advisory; the field names are pinned across the language line in
  // tests/test_own_clear.py.
  clear_refused?: string // the engine's rejection text, the latest
  clear_refusals?: number // how many asks the engine rejected
  clear_refused_at?: string
  turns_since_ask?: number // main-loop turn ends since the ask with the clear still queued
  consumed_at?: string
  new_session_id?: string
  previous_session_id?: string | null // at a stale marking: the session this process was last in
  stale_because?: string
}

type Engine = EngineInterface

// Module state: a reload starts it over, and the marker's own state then decides.
let root: string | undefined
let clearedFor: string | undefined // the session this process asked to clear
let turnsSinceAsk = 0 // main-loop turn ends in that session since the ask (the queued clear's one turn among them)
let clearResolvedAt: number | undefined // when the engine took the ask (the promise resolved) with the session still standing
let lastId: string | undefined // the session this process was in at its last event
let logChain: Promise<void> = Promise.resolve() // the log's writes, one after another (read-whole then write-whole)

// A line in the log the environment names, or nothing; never rejects (it runs
// in continuations the hook did not await, after the hook has answered). The
// writes are chained: each is a read of the whole file then a write of the
// whole, and two in flight at once (a continuation beside a handler) would
// drop a line.
function note($: Engine, text: string): Promise<void> {
  const run = () => noteNow($, text)
  return (logChain = logChain.then(run, run))
}

async function noteNow($: Engine, text: string): Promise<void> {
  try {
    const log = await $.env.get('ESPALIER_OWN_CLEAR_LOG')
    if (!log) return
    let prev = ''
    try {
      prev = await $.fs.read(log)
    } catch {
      prev = ''
    }
    let body = prev + JSON.stringify({ t: await $.clock.now(), text }) + '\n'
    if (body.length > LOG_BYTES) body = body.split('\n').slice(-LOG_KEEP - 1).join('\n')
    await $.fs.write(log, body)
  } catch {
    // the log is a convenience; a refused read or write costs nothing
  }
}

async function git($: Engine, cwd: string, ...argv: string[]): Promise<{ ok: boolean; out: string }> {
  try {
    const r = await $.process.run(['git', ...argv], { cwd, timeoutMs: 10000 })
    return { ok: r.exitCode === 0, out: r.stdout.trim() }
  } catch (err) {
    return { ok: false, out: String(err) }
  }
}

async function repoRoot($: Engine): Promise<string> {
  // A root the environment names is read every time (a test or a drive sets
  // it per session); only the one git answers is cached.
  const given = await $.env.get('ESPALIER_OWN_CLEAR_ROOT')
  if (given) return given
  if (root) return root
  const cwd = await $.session.cwd()
  const top = await git($, cwd, 'rev-parse', '--show-toplevel')
  return (root = top.ok && top.out ? top.out : cwd)
}

async function readMarker($: Engine): Promise<Marker | undefined> {
  const path = `${await repoRoot($)}/${MARKER}`
  try {
    if (!(await $.fs.exists(path))) return undefined
    const parsed: unknown = JSON.parse(await $.fs.read(path))
    return parsed && typeof parsed === 'object' ? (parsed as Marker) : undefined
  } catch {
    return undefined
  }
}

async function writeMarker($: Engine, marker: Marker): Promise<void> {
  await $.fs.write(`${await repoRoot($)}/${MARKER}`, JSON.stringify(marker, null, 2) + '\n')
}

// A field on the marker's record; a marker that cannot take it costs a log
// line, never the hook (DEF-5031: the record is what outlives the process).
async function record($: Engine, id: string, fields: Partial<Marker>, what: string): Promise<void> {
  try {
    // Read again right before the write: the handler that called this read the
    // marker before two git spawns, and the clear's SessionStart may have
    // consumed it in between (DEF-5032's 5 ms window, from the other side); a
    // write from the older copy would arm it again for a dead session.
    const current = await readMarker($)
    if (!armedFor(current, id)) return
    await writeMarker($, { ...current, ...fields })
  } catch (err) {
    await note($, `the marker could not take ${what} (${String(err)})`)
  }
}

// A marker's own ask within the last day: what stands in for this process's
// memory after a reload (DEF-5032), bounded so a leftover of a window long
// closed is never taken as ours.
const RELOAD_ASK_WINDOW_MS = 24 * 60 * 60 * 1000
function recentAsk(marker: Marker, now: number): boolean {
  if (typeof marker.clear_asked_at !== 'string' || !marker.clear_asked_at) return false
  const at = Date.parse(marker.clear_asked_at)
  return Number.isFinite(at) && now - at >= 0 && now - at <= RELOAD_ASK_WINDOW_MS
}

function armedFor(marker: Marker | undefined, id: string): marker is Marker {
  return !!marker && marker.state === 'armed' && marker.session_id === id
}

// Why the clear must wait, or '' when nothing is in flight: the handoff gate's
// predicate (tools/cc/hooks/stop_gate.py, Gate 5) read from this side, plus
// HEAD unmoved since the handoff (a commit after it means a handoff is owed
// again, and that handoff re-arms the marker with the new head). Three
// callers: clearable, at the ask and at a compaction, and the clear's
// SessionStart, which reads it BEFORE the project's settings hooks run beneath
// it, so everything read here must be the old window's own state as the
// handoff left it; a predicate about the base (a merge-base, the remote tip)
// would read the checkout before the catch-up there and belongs elsewhere.
async function inFlight($: Engine, marker: Marker): Promise<string> {
  const cwd = await repoRoot($)
  const status = await git($, cwd, 'status', '--porcelain', '--untracked-files=no')
  if (!status.ok) return `git status could not be read (${status.out || 'no output'})`
  if (status.out) return 'a tracked edit is in flight'
  const head = await git($, cwd, 'rev-parse', 'HEAD')
  if (!head.ok) return 'HEAD could not be read'
  if (marker.head && head.out !== marker.head) return 'HEAD moved since the handoff (that handoff re-arms the marker)'
  try {
    const plan: unknown = JSON.parse(await $.fs.read(`${cwd}/${PLAN}`))
    const p = plan as { status?: unknown; steps?: unknown }
    if (p && p.status === 'in_progress' && Array.isArray(p.steps) && p.steps.length) return 'a plan is in progress'
  } catch {
    // no plan file, or one that does not parse: nothing in progress
  }
  return ''
}

// The marker armed for `id`, and why its clear must wait ('' when it can run).
async function clearable($: Engine, id: string): Promise<{ marker?: Marker; why: string }> {
  const marker = await readMarker($)
  if (!armedFor(marker, id)) return { why: 'not armed for this session' }
  return { marker, why: await inFlight($, marker) }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    // Once per process (a /clear raises no second session.start, measured
    // 2026-10-26): nothing is cleared yet, and the root is read afresh.
    root = undefined
    const id = await $.session.id()
    // Measured on 2.1.310: a /clear raises no second session.start. Should a
    // later engine raise one, it would hand the NEW id to the clear's
    // SessionStart as this process's last and the mod would read its own
    // marker as another window's (DEF-5032): under a pending clear the last
    // session stays the asked one, and the ask itself is kept for that
    // SessionStart to read.
    if (clearedFor === undefined) {
      turnsSinceAsk = 0
      clearResolvedAt = undefined
      lastId = id
    }
    await repoRoot($)
    return next(e)
  }).catch(($, e, next) => next(e))

  on('turn.complete', async ($, e, next) => {
    if (e.agentId !== undefined) return next(e)
    const id = await $.session.id()
    // The session this process was last in, for the clear's SessionStart to
    // compare the marker with -- except under a clear this process asked and
    // is still waiting on: the session is then either still the asked one
    // (lastId already names it) or the queued clear is flipping it under this
    // handler, whose session.id() reads the NEW id. Taken here, that id made
    // the clear's SessionStart read its own marker as another window's, mark
    // it stale and re-prime nothing (DEF-5032: the worker window 19cab033,
    // 2026-10-30, the clear dequeued 5 ms after the tick turn's end). The
    // clear's SessionStart sets the new id itself.
    if (clearedFor === undefined || id === clearedFor) lastId = id
    if (e.reason !== 'answer') return next(e)
    if (clearedFor === id) {
      // Asked already, and the session is still this one, so the clear has
      // not run. Measured 2026-10-30 on 2.1.314: a prompt queued while the
      // asking turn ran (a loop tick) is dequeued first, the engine queues the
      // clear behind it and runs it when that turn ends. It is never asked
      // again while this session stands: with two prompts queued ahead, a
      // second ask would be a second clear, wiping the window the first one
      // re-primes. The status line names the queued clear and what this turn
      // left in flight (the queued clear runs over it: the clear's
      // SessionStart says so to the new window), a compaction is let through
      // once two turns have passed (session.compact, below), so a clear the
      // engine lost never freezes the window, and the operator's own /clear
      // ends the wait.
      turnsSinceAsk += 1
      const { marker, why } = await clearable($, id)
      const left = marker && why ? `; this turn left ${why} (the queued clear runs anyway)` : ''
      $.ui.status(QUEUED_STATUS + left)
      // On the record: the turns the clear has waited and, once the engine
      // has answered the ask with the session still standing, when -- a taken
      // clear that never runs reads apart from a queued one and a refused one
      // (DEF-5031; the banner's Own-clear: line tells the three).
      if (marker) {
        const taken = clearResolvedAt === undefined ? {} : { clear_resolved_at: new Date(clearResolvedAt).toISOString() }
        await record($, id, { turns_since_ask: turnsSinceAsk, ...taken }, 'the queued turn count')
      }
      await note($, `turn.complete: the clear asked for ${id} has not run after ${turnsSinceAsk} more turn(s)${left}`)
      return next(e)
    }
    const { marker, why } = await clearable($, id)
    if (!marker) return next(e)
    if (why) {
      $.ui.status(`own-clear: armed, waiting: ${why}`)
      await note($, `turn.complete: armed for ${id}, waiting: ${why}`)
      return next(e)
    }
    clearedFor = id
    turnsSinceAsk = 0
    clearResolvedAt = undefined
    $.ui.status(undefined)
    $.ui.toast('own-clear: the handoff landed; clearing this window and re-priming it')
    await note($, `turn.complete: clearing for ${id}`)
    try {
      // The ask on the record (the banner's Own-clear: line, the prompt
      // router and this module's own reload arm read it; the marker on disk
      // is what outlives this process when a clear never comes), and an
      // earlier ask's fields taken off it (JSON drops an undefined field): a
      // refusal recorded on ask 1 must not read as ask 2's, which the engine
      // may take. The count stays, cumulative.
      await writeMarker($, {
        ...marker, clear_asked_at: new Date(await $.clock.now()).toISOString(),
        clear_refused: undefined, clear_refused_at: undefined, clear_resolved_at: undefined, turns_since_ask: undefined,
      })
    } catch (err) {
      await note($, `the marker could not take the ask (${String(err)}); clearing anyway`)
    }
    $.command
      .run({ command: 'clear', args: '' })
      .then(async r => {
        // The engine took the ask. With the session still standing (a queued
        // clear, or one taken and never run) the next turn's end puts the time
        // on the record; module state only here, since a write from this
        // continuation could race the clear's SessionStart over the marker.
        // The two handlers are the two arguments of one then(), so a throw in
        // this one is never read as a refusal by the other.
        try {
          if (clearedFor === id) clearResolvedAt = await $.clock.now()
        } catch {
          // no clock: the record goes without the time
        }
        let shown = ''
        try {
          shown = JSON.stringify(r).slice(0, 200)
        } catch {
          shown = '(a result JSON cannot print)'
        }
        return note($, `command.run(clear) resolved: ${shown}`)
      }, async err => {
        // Not cleared: say so where the operator looks, put it on the record
        // the process does not keep, and let the next turn's end try again
        // (the marker is still armed). The dispatcher window 88a94ba9 re-asked
        // 41 times over ten hours with the refusal on this status line alone
        // and the log off (DEF-5031): the marker now carries the engine's
        // reason, when, and the count, for the banner's Own-clear: line and
        // the prompt router's advisory to read. The whole body is guarded: a
        // continuation the hook did not await must never reject, and a late
        // rejection of an ask from a session since cleared resets nothing.
        try {
          const reason = String(err)
          if (clearedFor === id) {
            clearedFor = undefined
            turnsSinceAsk = 0
            clearResolvedAt = undefined
          }
          $.ui.status(FAILED_STATUS) // at once; the count follows the record below
          let count = 1
          try {
            const current = await readMarker($)
            if (armedFor(current, id)) {
              count = (typeof current.clear_refusals === 'number' ? current.clear_refusals : 0) + 1
              await writeMarker($, {
                ...current, clear_refused: reason, clear_refusals: count,
                clear_refused_at: new Date(await $.clock.now()).toISOString(),
              })
            }
          } catch (e2) {
            await note($, `the marker could not take the refusal (${String(e2)})`)
          }
          $.ui.status(`${FAILED_STATUS} (refused ${count} time(s): ${reason})`)
          await note($, `command.run(clear) rejected: ${reason}`)
        } catch {
          // a status line or a clock that throws: nothing left to say
        }
      })
    return next(e)
  }).catch(($, e, next) => next(e))

  on('classic.SessionStart', async ($, e, next) => {
    // Before next(e): the project's settings hooks run beneath this one. A
    // sweep there must not take the marker before it is read, and the checkout
    // catch-up there (the banner's Checkout: line) moves a checkout whose lane
    // merged onto the base, so what the old window left in flight is read here
    // too, against the marker's head: read after the hand-on, the catch-up
    // named itself as a HEAD move on every re-prime whose lane had merged
    // (DEF-5028, 2026-10-30). Only for the marker this process's last session
    // armed; a stale one is marked below and nothing of it is read.
    // Read before the marker (three engine round-trips a turn's end could
    // land inside): the session this process was last in, and the one it
    // asked to clear while that ask stands.
    const before = lastId
    const asked = clearedFor
    const now = e.source === 'clear' ? await $.clock.now() : 0
    const marker = e.source === 'clear' ? await readMarker($) : undefined
    // Ours: armed for the session this process was last in, or for the one it
    // asked to clear (DEF-5032: the queued clear flipped the session under the
    // tick turn's end, whose handler then read the new id), or -- with no last
    // session known, a reload having reset this module -- a marker whose own
    // record says a mod in this checkout asked its clear within the last day
    // (a leftover of a window long closed is not taken; one seat per checkout
    // is the protocol's rule, and the bound is the floor under it). The one
    // predicate for the read here and for the stale branch below, so a
    // widening of one cannot turn the other off with no signal. The three arms
    // back each other up on purpose; each is pinned alone by text in
    // tests/test_own_clear.py.
    const ours = marker !== undefined && marker.state === 'armed' && (
      (before !== undefined && marker.session_id === before)
      || (asked !== undefined && marker.session_id === asked)
      || (before === undefined && recentAsk(marker, now)))
    let left = ''
    if (ours && marker) {
      try {
        left = await inFlight($, marker)
      } catch (err) {
        await note($, `classic.SessionStart source=clear: the in-flight read before the hand-on failed (${String(err)}); nothing named`)
      }
    }
    const r = await next(e)
    const id = await $.session.id()
    lastId = id
    if (e.source !== 'clear') return r
    // A clear came (this process's, or the operator's hand): no ask is pending
    // past it, so turn ends move lastId again (turn.complete, above).
    clearedFor = undefined
    turnsSinceAsk = 0
    clearResolvedAt = undefined
    $.ui.status(undefined)
    try {
      if (!marker || marker.state !== 'armed') return r
      const stamp = new Date(await $.clock.now()).toISOString()
      if (!ours) {
        // Armed by another window, or by a session this process never saw:
        // not this clear's. Marked, so no later clear re-primes on it either,
        // with the two ids compared on the record (DEF-5032: the banner's
        // Own-clear: line names a window cleared and not re-primed).
        const was = before ?? 'unknown (this process kept no last session: a reload resets it)'
        await writeMarker($, {
          ...marker, state: 'stale', consumed_at: stamp, new_session_id: id, previous_session_id: before ?? null,
          stale_because: `armed for ${marker.session_id}; this process's last session was ${was}`,
        })
        await note($, `classic.SessionStart source=clear: a marker of ${marker.session_id} is not this window's (${was}); marked stale`)
        return r
      }
      let brief = marker.brief && marker.brief.trim() ? marker.brief : GENERIC_BRIEF
      // A clear queued behind a prompt ran over whatever that turn did (the
      // in-flight check held only at the ask): the new window is told first,
      // from the read above the hand-on.
      if (left) {
        brief += `\n\nown-clear: at the clear, ${left} -- work in the old window after its handoff; read git status and git log -3 before anything else.`
      }
      try {
        await writeMarker($, { ...marker, state: 'consumed', consumed_at: stamp, new_session_id: id })
      } catch (err) {
        await note($, `the marker could not be rewritten (${String(err)}); re-priming anyway`)
      }
      await note($, `classic.SessionStart source=clear: consumed the marker of ${marker.session_id}; re-priming ${id}`)
      $.prompt
        .submit({ text: brief, asUser: true })
        .then(res => note($, `prompt.submit resolved: ${JSON.stringify(res).slice(0, 200)}`))
        .catch(err => note($, `prompt.submit rejected: ${String(err)}`))
    } catch (err) {
      await note($, `classic.SessionStart source=clear: ${String(err)}`)
    }
    return r
  }).catch(($, e, next) => next(e))

  on('session.compact', async ($, e, next) => {
    if (e.agentId !== undefined) return next(e)
    const id = await $.session.id()
    if (clearedFor !== id) {
      // Refused only when the clear can run: a held clear (an edit in flight, a
      // plan in progress, HEAD moved) lets the compaction through.
      const { marker, why } = await clearable($, id)
      if (!marker || why) return next(e)
    } else if (turnsSinceAsk >= 2) {
      // The clear asked two turns ago has not come. The refusal exists so the
      // handoff's summary is not written twice; held over a clear the engine
      // lost, it would fill the window instead. The compaction runs.
      await note($, `session.compact (${e.trigger}) let through: the clear asked for ${id} has not run after ${turnsSinceAsk} more turns`)
      return next(e)
    }
    await note($, `session.compact (${e.trigger}) refused: armed for ${id}`)
    return { skip: SKIP_REASON }
  }).catch(($, e, next) => next(e))
}
