import { expect, mock, test } from 'claude-code/testing'

// The own-clear's hooks against the engine (`claude plugin test`). Under test
// every call the mod makes on `$` is an event the test answers with `{ value }`,
// so the checkout is a world in memory: the files, git's three answers, the
// session id (which a test moves to stand for a clear), the clock and the
// status line, with the test's own hooks as the bottom of each chain the mod
// raises (command.run, prompt.submit, session.compact), recording what the
// mod asked for. The bottom of classic.SessionStart deletes the marker, so a
// mod that read it after next(e) would find nothing: that pins the order. The
// root reaches the mod through ESPALIER_OWN_CLEAR_ROOT, mocked before the
// plugin loads.

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
  const state = { id: opts.id ?? 'this-session', dirty: false, failWrites: false, refuseClear: false }
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
    if (argv === 'git rev-parse HEAD') return done(`${HEAD}\n`)
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
    files.delete(MARKER) // a sweep beneath the mod: the marker must have been read already
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

test('the clear runs once per session', async ($, on) => {
  const w = world(on)
  w.arm({ session_id: w.id(), head: HEAD })
  await $.turn.complete(TURN)
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
  w.arm({ session_id: w.id(), head: 'h' })
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
  w.arm({ session_id: w.id(), head: 'h', brief: null })
  w.state.id = 'the-new-session'
  await $.classic.SessionStart({ source: 'clear' })
  expect(w.seen.prompts.length).toBe(1)
  expect(w.seen.prompts[0]).toContain('cleared by the own-clear')
  expect(w.seen.prompts[0]).toContain('start no second one')
})

test('a marker armed for a session this process was never in is marked stale and re-primes nothing', async ($, on) => {
  const w = world(on)
  await $.classic.SessionStart({ source: 'startup' })
  w.arm({ session_id: 'someone-else', head: 'h' })
  w.state.id = 'the-new-session'
  await $.classic.SessionStart({ source: 'clear' })
  expect(w.seen.prompts).toEqual([])
  expect(w.marker().state).toBe('stale')
  expect(w.marker().session_id).toBe('someone-else')
})

test('a startup SessionStart, a consumed marker and no marker re-prime nothing', async ($, on) => {
  const w = world(on)
  w.arm({ session_id: w.id(), head: 'h' })
  await $.classic.SessionStart({ source: 'startup' })
  expect(w.seen.prompts).toEqual([])
  w.arm({ session_id: w.id(), head: 'h', state: 'consumed' })
  await $.classic.SessionStart({ source: 'clear' })
  expect(w.seen.prompts).toEqual([])
  await $.classic.SessionStart({ source: 'clear' })
  expect(w.seen.prompts).toEqual([])
})

test('a marker that cannot be rewritten still re-primes', async ($, on) => {
  const w = world(on)
  await $.classic.SessionStart({ source: 'startup' })
  w.arm({ session_id: w.id(), head: 'h' })
  w.state.id = 'the-new-session'
  w.state.failWrites = true
  await $.classic.SessionStart({ source: 'clear' })
  expect(w.seen.prompts).toEqual(['the seat brief'])
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
