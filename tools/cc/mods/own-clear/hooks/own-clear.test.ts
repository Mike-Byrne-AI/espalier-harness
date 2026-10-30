import { expect, mock, test } from 'claude-code/testing'

// The own-clear's hooks against the engine (`claude plugin test`). Under test
// every call the mod makes on `$` is an event the test answers with `{ value }`,
// so the checkout is a world in memory: the files, git's three answers, the
// session id (which a test moves to stand for a clear), the clock and the
// status line, with the test's own hooks as the bottom of each chain the mod
// raises (command.run, prompt.submit, session.compact), recording what the
// mod asked for. The bottom of classic.SessionStart deletes the marker, so a
// mod that read it after next(e) would find nothing, and moves HEAD when a
// test asks, standing for the checkout catch-up the project's SessionStart
// hook runs beneath the mod, so a mod that read what the old window left in
// flight after next(e) would name that move: both pin the order. The root
// reaches the mod through ESPALIER_OWN_CLEAR_ROOT, mocked before the plugin
// loads.

const ROOT = '/scratch'
const MARKER = `${ROOT}/.espalier-state/own_clear.json`
const PLAN = `${ROOT}/cc/execution_plan.json`
const HEAD = 'a1b2c3d4e5f60718293a4b5c6d7e8f9012345678'
const TURN = { answer: 'done', durationMs: 1, isAborted: false, turnId: 't-1', reason: 'answer' as const }

type Fields = Record<string, unknown>

function markerText(fields: Fields): string {
  return JSON.stringify({ state: 'armed', seat: 'box', role: 'worker', brief: 'the seat brief', written_at: 'now', ...fields }) + '\n'
}

function world(on: any, opts: { id?: string } = {}) {
  const state = { id: opts.id ?? 'this-session', head: HEAD, headBeneath: '', dirty: false, failWrites: false, refuseClear: false }
  const files = new Map<string, string>()
  const seen = { commands: [] as string[], prompts: [] as string[], compactions: 0, status: [] as (string | undefined)[], toasts: [] as string[] }
  const transcript = [{ role: 'user', text: 'Reply with the single word ready.', toolUses: [], handle: 'm-1' }]
  const done = (stdout: string, exitCode = 0) => ({ value: { exitCode, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })
  mock.env(on, { ESPALIER_OWN_CLEAR_ROOT: ROOT })
  on('session.id', () => ({ value: state.id }))
  on('session.cwd', () => ({ value: ROOT }))
  on('session.messages', () => ({ value: transcript }))
  on('clock.now', () => ({ value: 1793066349000 }))
  on('fs.exists', (_$: any, e: any) => ({ value: files.has(e.path) }))
  on('fs.read', (_$: any, e: any) => ({ value: files.get(e.path) ?? '' }))
  on('fs.write', (_$: any, e: any) => {
    if (state.failWrites) throw new Error('read-only')
    files.set(e.path, e.text)
    return { value: undefined }
  })
  on('process.run', (_$: any, e: any) => {
    const argv = e.argv.join(' ')
    if (argv === 'git status --porcelain --untracked-files=no') return done(state.dirty ? ' M tracked.txt\n' : '')
    if (argv === 'git rev-parse HEAD') return done(`${state.head}\n`)
    if (argv === 'git rev-parse --show-toplevel') return done(`${ROOT}\n`)
    return done('', 1)
  })
  on('ui.status', (_$: any, e: any) => {
    seen.status.push(e.text)
    return { value: undefined }
  })
  on('ui.toast', (_$: any, e: any) => {
    seen.toasts.push(e.text)
    return { value: undefined }
  })
  on('session.start', (_$: any, e: any) => ({ cwd: e.cwd }))
  on('turn.complete', (_$: any, e: any) => ({ text: e.answer }))
  on('classic.SessionStart', () => {
    // The hooks beneath the mod: a sweep that takes the marker (it must have
    // been read already) and the checkout catch-up that moves HEAD when a test
    // asks (what the old window left in flight must have been read already).
    files.delete(MARKER)
    if (state.headBeneath) state.head = state.headBeneath
    return {}
  })
  on('command.run', (_$: any, e: any) => {
    seen.commands.push(e.command)
    if (e.command === 'clear' && state.refuseClear) throw new Error('a Stop stands')
    return { text: '' }
  })
  on('prompt.submit', (_$: any, e: any) => {
    seen.prompts.push(e.text)
    return { text: e.text }
  })
  on('session.compact', (_$: any, e: any) => {
    seen.compactions += 1
    return { messages: e.messages }
  })
  const arm = (fields: Fields) => files.set(MARKER, markerText(fields))
  const marker = () => JSON.parse(files.get(MARKER) ?? 'null')
  const compact = ($: any) => $.session.compact({ trigger: 'manual', messages: transcript } as any)
  return { state, files, seen, arm, marker, compact, id: () => state.id }
}

test('an armed marker for this session clears at the end of the turn', async ($, on) => {
  const w = world(on)
  w.arm({ session_id: w.id(), head: HEAD })
  await $.turn.complete(TURN)
  expect(w.seen.commands).toEqual(['clear'])
  expect(w.seen.toasts.length).toBe(1)
  expect(w.marker().state).toBe('armed')
})

test('a marker for another session clears nothing', async ($, on) => {
  const w = world(on)
  w.arm({ session_id: 'someone-else', head: HEAD })
  await $.turn.complete(TURN)
  expect(w.seen.commands).toEqual([])
})

test('no marker clears nothing', async ($, on) => {
  const w = world(on)
  await $.turn.complete(TURN)
  expect(w.seen.commands).toEqual([])
})

test('a tracked edit in flight keeps the marker armed, names the wait, and clears nothing', async ($, on) => {
  const w = world(on)
  w.state.dirty = true
  w.arm({ session_id: w.id(), head: HEAD })
  await $.turn.complete(TURN)
  expect(w.seen.commands).toEqual([])
  expect(w.seen.status.at(-1)).toContain('a tracked edit is in flight')
  expect(w.marker().state).toBe('armed')
})

test('HEAD moved since the handoff clears nothing', async ($, on) => {
  const w = world(on)
  w.arm({ session_id: w.id(), head: '0f1e2d3c4b5a69788796a5b4c3d2e1f098765432' })
  await $.turn.complete(TURN)
  expect(w.seen.commands).toEqual([])
  expect(w.seen.status.at(-1)).toContain('HEAD moved')
})

test('a plan in progress clears nothing; a complete one does not hold the clear', async ($, on) => {
  const w = world(on)
  w.arm({ session_id: w.id(), head: HEAD })
  w.files.set(PLAN, JSON.stringify({ status: 'in_progress', steps: [{ n: 1 }] }))
  await $.turn.complete(TURN)
  expect(w.seen.commands).toEqual([])
  expect(w.seen.status.at(-1)).toContain('a plan is in progress')
  w.files.set(PLAN, JSON.stringify({ status: 'complete', steps: [{ n: 1 }] }))
  await $.turn.complete(TURN)
  expect(w.seen.commands).toEqual(['clear'])
})

test('a subagent turn and an aborted turn clear nothing', async ($, on) => {
  const w = world(on)
  w.arm({ session_id: w.id(), head: HEAD })
  await $.turn.complete({ ...TURN, agentId: 'agent-1' })
  await $.turn.complete({ ...TURN, reason: 'aborted', isAborted: true })
  expect(w.seen.commands).toEqual([])
})

test("a clear asked at a turn's end is named, never asked again, while the session stands", async ($, on) => {
  // Measured 2026-10-30 on 2.1.314 (the dispatcher seat, 02:08Z): a prompt
  // queued while the handoff's turn ran (a loop tick) was dequeued 150 ms after
  // the turn ended, the mod's clear was enqueued behind it, and the engine ran
  // that clear when the tick's turn ended, two minutes on. A second ask at the
  // tick turn's end would have cleared the re-primed window, and with two
  // prompts queued no turn count tells a queued clear from a lost one. So every
  // later turn's end in the same session names the queued clear, and what the
  // turn left in flight, and asks nothing.
  const w = world(on)
  w.arm({ session_id: w.id(), head: HEAD })
  await $.turn.complete(TURN)
  expect(w.seen.commands).toEqual(['clear'])
  expect(w.marker().clear_asked_at).toBe(new Date(1793066349000).toISOString())
  await $.turn.complete(TURN)
  expect(w.seen.commands).toEqual(['clear'])
  expect(w.seen.status.at(-1)).toContain('queued')
  w.state.dirty = true
  await $.turn.complete(TURN)
  expect(w.seen.commands).toEqual(['clear'])
  expect(w.seen.status.at(-1)).toContain('a tracked edit is in flight')
  expect(w.marker().state).toBe('armed')
})

test('a compaction is let through once two turns have passed since the ask', async ($, on) => {
  // The compaction's refusal exists so the handoff's summary is not written
  // twice; held for ever over a clear the engine lost, it would freeze the
  // window instead. Two turns after the ask the clear is evidently not coming
  // at this turn's end, and the compaction runs.
  const w = world(on)
  w.arm({ session_id: w.id(), head: HEAD })
  await $.turn.complete(TURN)
  expect((await w.compact($)).skip).toContain('own-clear')
  await $.turn.complete(TURN)
  expect((await w.compact($)).skip).toContain('own-clear')
  await $.turn.complete(TURN)
  expect((await w.compact($)).skip).toBeUndefined()
  expect(w.seen.compactions).toBe(1)
})

test("the clear's SessionStart names what the old window left in flight", async ($, on) => {
  // A queued clear runs over whatever the turn before it did: the new window
  // is told, after its brief, before it reads anything else.
  const w = world(on)
  await $.classic.SessionStart({ source: 'startup' })
  w.arm({ session_id: w.id(), head: HEAD })
  w.state.id = 'the-new-session'
  w.state.dirty = true
  await $.classic.SessionStart({ source: 'clear' })
  expect(w.seen.prompts.length).toBe(1)
  expect(w.seen.prompts[0]).toContain('the seat brief')
  expect(w.seen.prompts[0]).toContain('a tracked edit is in flight')
})

test('a marker that cannot take the ask still clears', async ($, on) => {
  const w = world(on)
  w.arm({ session_id: w.id(), head: HEAD })
  w.state.failWrites = true
  await $.turn.complete(TURN)
  expect(w.seen.commands).toEqual(['clear'])
})

test('a refused clear says so on the status line and is tried again at the next turn', async ($, on) => {
  const w = world(on)
  w.state.refuseClear = true
  w.arm({ session_id: w.id(), head: HEAD })
  await $.turn.complete(TURN)
  expect(w.seen.commands).toEqual(['clear'])
  expect(w.seen.status.at(-1)).toContain('the clear was refused')
  w.state.refuseClear = false
  await $.turn.complete(TURN)
  expect(w.seen.commands).toEqual(['clear', 'clear'])
})

test("the clear's SessionStart consumes the marker of the session this process was in and submits its brief", async ($, on) => {
  const w = world(on)
  await $.classic.SessionStart({ source: 'startup' }) // the process learns its session
  w.arm({ session_id: w.id(), head: HEAD })
  w.state.id = 'the-new-session'
  await $.classic.SessionStart({ source: 'clear' })
  expect(w.seen.prompts).toEqual(['the seat brief'])
  expect(w.marker().state).toBe('consumed')
  expect(w.marker().new_session_id).toBe('the-new-session')
  expect(w.marker().session_id).toBe('this-session')
  expect(w.seen.status.at(-1)).toBeUndefined()
})

test('a marker with no brief re-primes with the generic line', async ($, on) => {
  const w = world(on)
  await $.classic.SessionStart({ source: 'startup' })
  w.arm({ session_id: w.id(), head: HEAD, brief: null })
  w.state.id = 'the-new-session'
  await $.classic.SessionStart({ source: 'clear' })
  expect(w.seen.prompts.length).toBe(1)
  expect(w.seen.prompts[0]).toContain('cleared by the own-clear')
  expect(w.seen.prompts[0]).toContain('start no second one')
})

test('a marker armed for a session this process was never in is marked stale and re-primes nothing', async ($, on) => {
  const w = world(on)
  await $.classic.SessionStart({ source: 'startup' })
  w.arm({ session_id: 'someone-else', head: HEAD })
  w.state.id = 'the-new-session'
  await $.classic.SessionStart({ source: 'clear' })
  expect(w.seen.prompts).toEqual([])
  expect(w.marker().state).toBe('stale')
  expect(w.marker().session_id).toBe('someone-else')
})

test('a startup SessionStart, a consumed marker and no marker re-prime nothing', async ($, on) => {
  const w = world(on)
  w.arm({ session_id: w.id(), head: HEAD })
  await $.classic.SessionStart({ source: 'startup' })
  expect(w.seen.prompts).toEqual([])
  w.arm({ session_id: w.id(), head: HEAD, state: 'consumed' })
  await $.classic.SessionStart({ source: 'clear' })
  expect(w.seen.prompts).toEqual([])
  await $.classic.SessionStart({ source: 'clear' })
  expect(w.seen.prompts).toEqual([])
})

test('a marker that cannot be rewritten still re-primes', async ($, on) => {
  const w = world(on)
  await $.classic.SessionStart({ source: 'startup' })
  w.arm({ session_id: w.id(), head: HEAD })
  w.state.id = 'the-new-session'
  w.state.failWrites = true
  await $.classic.SessionStart({ source: 'clear' })
  expect(w.seen.prompts).toEqual(['the seat brief'])
})

test("a marker whose head moved re-primes with the move named", async ($, on) => {
  // The old window committed after its handoff (the handoff re-arms on its
  // own; a hand commit does not): the new window hears it before anything.
  const w = world(on)
  await $.classic.SessionStart({ source: 'startup' })
  w.arm({ session_id: w.id(), head: 'h' })
  w.state.id = 'the-new-session'
  await $.classic.SessionStart({ source: 'clear' })
  expect(w.seen.prompts.length).toBe(1)
  expect(w.seen.prompts[0]).toContain('HEAD moved since the handoff')
})

test("the clear's SessionStart reads what the old window left in flight before the hooks beneath move HEAD", async ($, on) => {
  // The project's SessionStart hook runs inside next(e) and catches the
  // checkout up (the banner's Checkout: line): a lane branch GitHub deleted
  // at the merge moves onto the base. Read after next(e), that move named
  // itself as work left in the old window on every re-prime whose lane had
  // merged (the dispatcher window 28cea670, 2026-10-30: six tool calls on a
  // clean tree). The old window's final state is read beside the marker,
  // before the event is handed on.
  const w = world(on)
  await $.classic.SessionStart({ source: 'startup' })
  w.arm({ session_id: w.id(), head: HEAD })
  w.state.id = 'the-new-session'
  w.state.headBeneath = '0f1e2d3c4b5a69788796a5b4c3d2e1f098765432'
  await $.classic.SessionStart({ source: 'clear' })
  expect(w.state.head).toBe(w.state.headBeneath) // the stage beneath ran
  expect(w.seen.prompts.length).toBe(1)
  expect(w.seen.prompts[0].includes('HEAD moved')).toBe(false)
  expect(w.marker().state).toBe('consumed')
})

test('a compaction is refused only while the marker is armed and the clear can run, or is under way', async ($, on) => {
  const w = world(on)
  w.arm({ session_id: w.id(), head: HEAD })
  expect((await w.compact($)).skip).toContain('own-clear')
  expect(w.seen.compactions).toBe(0)
  w.state.dirty = true // the clear is on hold: the compaction runs
  expect((await w.compact($)).skip).toBeUndefined()
  expect(w.seen.compactions).toBe(1)
  w.state.dirty = false
  await $.turn.complete(TURN) // the clear is under way
  expect(w.seen.commands).toEqual(['clear'])
  w.arm({ session_id: 'someone-else', head: HEAD })
  expect((await w.compact($)).skip).toContain('own-clear')
  expect(w.seen.compactions).toBe(1)
})

test('a compaction runs when nothing is armed for this session', async ($, on) => {
  const w = world(on)
  w.arm({ session_id: 'someone-else', head: HEAD })
  expect((await w.compact($)).skip).toBeUndefined()
  expect(w.seen.compactions).toBe(1)
})

// The record (DEF-5031, DEF-5032, 2026-10-30): the mod's log is opt-in and was
// off on every seat, so a clear the engine refused 41 times over ten hours on
// the dispatcher window (88a94ba9, 2.1.312) and a re-prime the mod skipped on a
// worker window (19cab033) left nothing a reader could find but a status line
// nobody read. Every outcome goes on the marker, which outlives the process;
// the banner's Own-clear: line reads it. The continuation that records a
// refusal runs after the hook has answered, so a case waits for it, bounded.
async function until(pred: () => boolean, tries = 50): Promise<void> {
  for (let i = 0; i < tries && !pred(); i++) await new Promise(r => setTimeout(r, 5))
}

test("a refused clear is on the marker's record: the reason, when, and a count that grows", async ($, on) => {
  const w = world(on)
  w.state.refuseClear = true
  w.arm({ session_id: w.id(), head: HEAD })
  await $.turn.complete(TURN)
  await until(() => w.marker().clear_refusals !== undefined)
  expect(w.marker().state).toBe('armed')
  // the engine's own rejection text (under test, the thrown hook reads as no implementation)
  expect(w.marker().clear_refused).toContain('command.run')
  expect(w.marker().clear_refusals).toBe(1)
  expect(w.marker().clear_refused_at).toBe(new Date(1793066349000).toISOString())
  expect(w.seen.status.at(-1)).toContain('the clear was refused')
  await $.turn.complete(TURN)
  await until(() => w.marker().clear_refusals === 2)
  expect(w.marker().clear_refusals).toBe(2)
  expect(w.seen.commands).toEqual(['clear', 'clear'])
})

test('the turns a queued clear has waited are counted on the marker', async ($, on) => {
  const w = world(on)
  w.arm({ session_id: w.id(), head: HEAD })
  await $.turn.complete(TURN)
  expect(w.marker().turns_since_ask).toBeUndefined()
  await $.turn.complete(TURN)
  expect(w.marker().turns_since_ask).toBe(1)
  await $.turn.complete(TURN)
  expect(w.marker().turns_since_ask).toBe(2)
  expect(w.seen.commands).toEqual(['clear'])
})

test("a turn that ends as the queued clear flips the session keeps the asked session as this process's last", async ($, on) => {
  // DEF-5032: the handoff's turn asked the clear; a loop tick queued as it
  // ended ran first; the engine dequeued the clear 5 ms after the tick turn's
  // end, while that turn's turn.complete was still resolving session.id(),
  // which read the NEW id -- so the clear's SessionStart compared the marker
  // with the new session, marked it stale and re-primed nothing (the worker
  // window 19cab033, 19:55Z). Under a pending clear a turn's end moves nothing;
  // the clear's SessionStart sets the new id itself.
  const w = world(on)
  await $.classic.SessionStart({ source: 'startup' })
  w.arm({ session_id: w.id(), head: HEAD })
  await $.turn.complete(TURN) // the ask; the clear is queued behind the tick
  expect(w.seen.commands).toEqual(['clear'])
  w.state.id = 'the-new-session' // the dequeued clear flips the session...
  await $.turn.complete(TURN) // ...as the tick turn's end resolves its id
  await $.classic.SessionStart({ source: 'clear' })
  expect(w.seen.prompts).toEqual(['the seat brief'])
  expect(w.marker().state).toBe('consumed')
  expect(w.marker().new_session_id).toBe('the-new-session')
  expect(w.seen.commands).toEqual(['clear']) // and no second ask
})

test('a stale marking records the two ids it compared', async ($, on) => {
  const w = world(on)
  await $.classic.SessionStart({ source: 'startup' })
  w.arm({ session_id: 'someone-else', head: HEAD })
  w.state.id = 'the-new-session'
  await $.classic.SessionStart({ source: 'clear' })
  expect(w.marker().state).toBe('stale')
  expect(w.marker().previous_session_id).toBe('this-session')
  expect(w.marker().stale_because).toContain('someone-else')
  expect(w.marker().stale_because).toContain('this-session')
})

test("a clear that raises session.start keeps the asked session as this process's last", async ($, on) => {
  // Measured on 2.1.310 a /clear raises no second session.start (the mod's
  // once-per-process note); should a later engine raise one at the clear, it
  // would hand the new id to the clear's SessionStart as the last session.
  const w = world(on)
  await $.classic.SessionStart({ source: 'startup' })
  w.arm({ session_id: w.id(), head: HEAD })
  await $.turn.complete(TURN)
  expect(w.seen.commands).toEqual(['clear'])
  w.state.id = 'the-new-session'
  await $.session.start({ cwd: ROOT } as any)
  await $.classic.SessionStart({ source: 'clear' })
  expect(w.seen.prompts).toEqual(['the seat brief'])
  expect(w.marker().state).toBe('consumed')
})

test("after a reload a marker this checkout's mod asked to clear is still ours; one nobody asked is not", async ($, on) => {
  // A reload of the module (the engine reloads a plugin whose files changed)
  // resets its memory: no last session, no pending ask. The marker's own
  // record of the ask stands in for them; a marker with no ask on it is
  // another window's and stays stale.
  const w = world(on)
  w.arm({ session_id: 'the-asked-session', head: HEAD, clear_asked_at: '2026-10-30T19:55:41.420Z' })
  w.state.id = 'the-new-session'
  await $.classic.SessionStart({ source: 'clear' })
  expect(w.seen.prompts).toEqual(['the seat brief'])
  expect(w.marker().state).toBe('consumed')
  w.arm({ session_id: 'another-window', head: HEAD })
  w.state.id = 'a-third-session'
  await $.classic.SessionStart({ source: 'clear' })
  expect(w.seen.prompts).toEqual(['the seat brief'])
  expect(w.marker().state).toBe('stale')
  expect(w.marker().stale_because).toContain('another-window')
})

test('a clear the engine took and never ran is told apart from a queued one on the record', async ($, on) => {
  const w = world(on)
  w.arm({ session_id: w.id(), head: HEAD })
  await $.turn.complete(TURN) // the ask; the test's command.run answers at once
  await new Promise(r => setTimeout(r, 10)) // the resolution's continuation
  await $.turn.complete(TURN) // the session still stands: the clear did not run
  expect(w.marker().turns_since_ask).toBe(1)
  expect(w.marker().clear_resolved_at).toBe(new Date(1793066349000).toISOString())
  expect(w.marker().clear_refused).toBeUndefined()
  expect(w.marker().state).toBe('armed')
})
