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
//     status line; a clear the engine refuses says so there and is tried again
//     at the next turn's end;
//   - on that SessionStart (classic.SessionStart, source=clear) the mod reads
//     the marker BEFORE handing the event on (the project's settings hooks run
//     beneath it), and only when the marker names the session this process was
//     in before the clear (a marker another window armed, or one this process
//     never knew, is marked stale and re-primes nothing) marks it consumed and
//     submits the brief as the first message of the new session (measured: it
//     lands 70 ms after the start);
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
  consumed_at?: string
  new_session_id?: string
}

type Engine = EngineInterface

// Module state: a reload starts it over, and the marker's own state then decides.
let root: string | undefined
let clearedFor: string | undefined // the session this process asked to clear
let turnsSinceAsk = 0 // main-loop turn ends in that session since the ask (the queued clear's one turn among them)
let lastId: string | undefined // the session this process was in at its last event

// A line in the log the environment names, or nothing; never rejects (it runs
// in continuations the hook did not await, after the hook has answered).
async function note($: Engine, text: string): Promise<void> {
  try {
    const log = await $.env.get('ESPALIER_OWN_CLEAR_LOG')
    if (!log) return
    let prev = ''
    try {
      prev = await $.fs.read(log)
    } catch {
      prev = ''
    }
    await $.fs.write(log, prev + JSON.stringify({ t: await $.clock.now(), text }) + '\n')
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

function armedFor(marker: Marker | undefined, id: string): marker is Marker {
  return !!marker && marker.state === 'armed' && marker.session_id === id
}

// Why the clear must wait, or '' when nothing is in flight: the handoff gate's
// predicate (tools/cc/hooks/stop_gate.py, Gate 5) read from this side, plus
// HEAD unmoved since the handoff (a commit after it means a handoff is owed
// again, and that handoff re-arms the marker with the new head).
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
    clearedFor = undefined
    turnsSinceAsk = 0
    lastId = await $.session.id()
    await repoRoot($)
    return next(e)
  }).catch(($, e, next) => next(e))

  on('turn.complete', async ($, e, next) => {
    if (e.agentId !== undefined) return next(e)
    const id = await $.session.id()
    lastId = id
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
    $.ui.status(undefined)
    $.ui.toast('own-clear: the handoff landed; clearing this window and re-priming it')
    await note($, `turn.complete: clearing for ${id}`)
    try {
      // The ask on the record (record only: nothing reads it back; the marker
      // on disk is what outlives this process when a clear never comes).
      await writeMarker($, { ...marker, clear_asked_at: new Date(await $.clock.now()).toISOString() })
    } catch (err) {
      await note($, `the marker could not take the ask (${String(err)}); clearing anyway`)
    }
    $.command
      .run({ command: 'clear', args: '' })
      .then(r => note($, `command.run(clear) resolved: ${JSON.stringify(r)}`))
      .catch(err => {
        // Not cleared: say so where the operator looks, and let the next
        // turn's end try again (the marker is still armed).
        clearedFor = undefined
        turnsSinceAsk = 0
        $.ui.status(FAILED_STATUS)
        return note($, `command.run(clear) rejected: ${String(err)}`)
      })
    return next(e)
  }).catch(($, e, next) => next(e))

  on('classic.SessionStart', async ($, e, next) => {
    // Before next(e): the project's settings hooks run beneath this one, and a
    // sweep there must not take the marker before it is read.
    const marker = e.source === 'clear' ? await readMarker($) : undefined
    const r = await next(e)
    const id = await $.session.id()
    const before = lastId
    lastId = id
    if (e.source !== 'clear') return r
    $.ui.status(undefined)
    try {
      if (!marker || marker.state !== 'armed') return r
      const stamp = new Date(await $.clock.now()).toISOString()
      if (marker.session_id !== before) {
        // Armed by another window, or by a session this process never saw:
        // not this clear's. Marked, so no later clear re-primes on it either.
        await writeMarker($, { ...marker, state: 'stale', consumed_at: stamp, new_session_id: id })
        await note($, `classic.SessionStart source=clear: a marker of ${marker.session_id} is not this window's (${before}); marked stale`)
        return r
      }
      let brief = marker.brief && marker.brief.trim() ? marker.brief : GENERIC_BRIEF
      // A clear queued behind a prompt ran over whatever that turn did (the
      // in-flight check held only at the ask): the new window is told first.
      const left = await inFlight($, marker)
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
