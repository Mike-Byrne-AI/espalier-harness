import { expect, mock, test } from 'claude-code/testing'

// The own-clear's hooks against the engine (`claude plugin test`). Under test
// every call the mod makes on `$` is an event the test answers with `{ value }`
// (or `{ deny }`, standing for the engine's rejection), so the checkout is a
// world in memory: the files, git's three answers or a failure a case sets, the
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

// The engine hands an fs.* hook the path as it resolved it on the host: on
// Windows the mod's '/scratch/...' arrives as 'C:\scratch\...' (2.1.311 to
// 2.1.314, measured 2026-10-31). So the world's files are one store that keys
// every path one way, separators read as '/' and a leading drive letter
// dropped, and the test's literals and the engine's spellings meet in it; a
// POSIX literal keys as itself.
const key = (path: string) => path.replace(/\\/g, '/').replace(/^[A-Za-z]:(?=\/)/, '')

class Files extends Map<string, string> {
  override get(path: string) {
    return super.get(key(path))
  }
  override set(path: string, text: string) {
    return super.set(key(path), text)
  }
  override has(path: string) {
    return super.has(key(path))
  }
  override delete(path: string) {
    return super.delete(key(path))
  }
}

type Fields = Record<string, unknown>

function markerText(fields: Fields): string {
  return JSON.stringify({ state: 'armed', seat: 'box', role: 'worker', brief: 'the seat brief', written_at: 'now', ...fields }) + '\n'
}

// A git read that fails, keyed by its argv: git's exit and stderr, or a deny
// standing for the engine's rejection (git could not start, or outran its timeout).
type GitFailure = { exitCode?: number; stderr?: string; deny?: string }

function world(on: any, opts: { id?: string; env?: Record<string, string> } = {}) {
  const state = {
    id: opts.id ?? 'this-session', head: HEAD, headBeneath: '', dirty: false, failWrites: false, refuseClear: false,
    consumeDuringGit: false, gitFails: {} as Record<string, GitFailure>,
  }
  const files = new Files()
  const seen = { commands: [] as string[], prompts: [] as string[], compactions: 0, status: [] as (string | undefined)[], toasts: [] as string[] }
  const transcript = [{ role: 'user', text: 'Reply with the single word ready.', toolUses: [], handle: 'm-1' }]
  const done = (stdout: string, exitCode = 0) => ({ value: { exitCode, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })
  mock.env(on, opts.env ?? { ESPALIER_OWN_CLEAR_ROOT: ROOT })
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
    if (state.consumeDuringGit && argv.startsWith('git status')) {
      // The clear's SessionStart consumes the marker while a turn end's handler
      // is between its read and its write (the other side of DEF-5032's window).
      files.set(MARKER, markerText({ session_id: state.id, head: state.head, state: 'consumed', new_session_id: 'the-new-session' }))
    }
    const fail = state.gitFails[argv]
    if (fail?.deny) return { deny: fail.deny }
    if (fail) return { value: { ...done('', fail.exitCode ?? 128).value, stderr: fail.stderr ?? '' } }
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

// Host-independent, so a POSIX seat reds on a store that stops keying too
// (the cases below red on Windows alone).
test('the world keys the engine spelling and the test literal as one file', async () => {
  const f = new Files()
  f.set('/scratch/a/b.json', 'x')
  expect(f.get('C:\\scratch\\a\\b.json')).toBe('x')
  expect(f.has('D:/scratch/a/b.json')).toBe(true)
  expect(f.has('/scratch/a/c.json')).toBe(false)
  expect(f.delete('C:\\scratch\\a\\b.json')).toBe(true)
  expect(f.has('/scratch/a/b.json')).toBe(false)
})

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
  w.arm({ session_id: 'the-asked-session', head: HEAD, clear_asked_at: new Date(1793066349000 - 60_000).toISOString() })
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

test('after a reload a marker nobody asked to clear is not ours', async ($, on) => {
  // The reload arm's negative twin, with no prior event in this module (the
  // failure-mode review, 2026-10-30: a twin that ran after a prior event had
  // a last session already known and never exercised the arm's own condition).
  const w = world(on)
  w.arm({ session_id: 'another-window', head: HEAD })
  w.state.id = 'the-new-session'
  await $.classic.SessionStart({ source: 'clear' })
  expect(w.seen.prompts).toEqual([])
  expect(w.marker().state).toBe('stale')
  expect(w.marker().previous_session_id).toBeNull()
})

test('after a reload a marker asked to clear more than a day ago is not ours', async ($, on) => {
  // The arm's bound: a leftover of a window long closed, found by a process
  // that reloaded before any turn end, is not re-primed into this window.
  const w = world(on)
  w.arm({ session_id: 'a-window-long-closed', head: HEAD, clear_asked_at: new Date(1793066349000 - 2 * 86_400_000).toISOString() })
  w.state.id = 'the-new-session'
  await $.classic.SessionStart({ source: 'clear' })
  expect(w.seen.prompts).toEqual([])
  expect(w.marker().state).toBe('stale')
})

test("an earlier ask's refusal and wait come off the marker at the next ask; the count stays", async ($, on) => {
  // A refusal recorded on ask 1 must not read as ask 2's, which the engine
  // may take (the code review, 2026-10-30: a queued clear reported as refused).
  const w = world(on)
  w.state.refuseClear = true
  w.arm({ session_id: w.id(), head: HEAD })
  await $.turn.complete(TURN)
  await until(() => w.marker().clear_refusals === 1)
  w.state.refuseClear = false
  await $.turn.complete(TURN) // the re-ask, taken this time
  expect(w.seen.commands).toEqual(['clear', 'clear'])
  expect(w.marker().clear_refused).toBeUndefined()
  expect(w.marker().clear_refused_at).toBeUndefined()
  expect(w.marker().clear_refusals).toBe(1)
  expect(w.marker().clear_asked_at).toBe(new Date(1793066349000).toISOString())
})

test("a queued turn's record write never arms again a marker the clear consumed meanwhile", async ($, on) => {
  const w = world(on)
  w.arm({ session_id: w.id(), head: HEAD })
  await $.turn.complete(TURN) // the ask
  w.state.consumeDuringGit = true // the consume lands between this turn end's read and its write
  await $.turn.complete(TURN)
  expect(w.marker().state).toBe('consumed')
  expect(w.marker().turns_since_ask).toBeUndefined()
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

// A held clear on the record (DEF-2039, 2026-11-01): the dispatcher window sat
// held on 'HEAD moved' for 9 h and 36 loop ticks with the hold on its status
// line alone, and the consumed marker read as never asked. Each held turn's
// end writes why, since when and how many turn ends, for the prompt router
// (which tells the held window the verb) and the banner's Own-clear: line.
test("a held clear is on the marker's record: why, since when, and the turn ends it has held; the ask takes it off", async ($, on) => {
  const w = world(on)
  w.state.dirty = true
  w.arm({ session_id: w.id(), head: HEAD })
  await $.turn.complete(TURN)
  expect(w.marker().clear_held).toBe('a tracked edit is in flight')
  expect(w.marker().clear_held_since).toBe(new Date(1793066349000).toISOString())
  expect(w.marker().clear_held_turns).toBe(1)
  await $.turn.complete(TURN)
  expect(w.marker().clear_held_turns).toBe(2)
  // the cause moves: the latest is named, the hold's start and its count kept
  w.state.dirty = false
  w.files.set(PLAN, JSON.stringify({ status: 'in_progress', steps: [{ n: 1 }] }))
  await $.turn.complete(TURN)
  expect(w.marker().clear_held).toBe('a plan is in progress')
  expect(w.marker().clear_held_turns).toBe(3)
  expect(w.marker().state).toBe('armed')
  expect(w.seen.commands).toEqual([])
  w.files.set(PLAN, JSON.stringify({ status: 'complete', steps: [{ n: 1 }] }))
  await $.turn.complete(TURN) // nothing in flight: the ask
  expect(w.seen.commands).toEqual(['clear'])
  expect(w.marker().clear_held).toBeUndefined()
  expect(w.marker().clear_held_since).toBeUndefined()
  expect(w.marker().clear_held_turns).toBeUndefined()
})

test("a held clear's start and count are read from the marker, so a reload keeps them", async ($, on) => {
  const since = new Date(1793066349000 - 9 * 3_600_000).toISOString()
  const w = world(on)
  w.arm({ session_id: w.id(), head: '0f1e2d3c4b5a69788796a5b4c3d2e1f098765432', clear_held: 'HEAD moved', clear_held_since: since, clear_held_turns: 36 })
  await $.turn.complete(TURN)
  expect(w.marker().clear_held).toContain('HEAD moved since the handoff')
  expect(w.marker().clear_held_since).toBe(since)
  expect(w.marker().clear_held_turns).toBe(37)
})

test("a held turn's record write never arms again a marker the clear consumed meanwhile", async ($, on) => {
  const w = world(on)
  w.state.dirty = true
  w.arm({ session_id: w.id(), head: HEAD })
  w.state.consumeDuringGit = true // the consume lands between this turn end's read and its write
  await $.turn.complete(TURN)
  expect(w.marker().state).toBe('consumed')
  expect(w.marker().clear_held).toBeUndefined()
})

// Why a git read failed (DEF-3019, 2026-10-31): the helper kept stdout alone,
// so win-2's 06:25Z re-prime said 'HEAD could not be read' while HEAD equalled
// the marker's head, and nothing on the brief, the status line or the log said
// why. Each read hands the world a failing value and reads the reason back.
test("a HEAD git cannot read holds the clear and names git's own words", async ($, on) => {
  const w = world(on)
  w.state.gitFails['git rev-parse HEAD'] = { exitCode: 128, stderr: 'fatal: bad object HEAD\n' }
  w.arm({ session_id: w.id(), head: HEAD })
  await $.turn.complete(TURN)
  expect(w.seen.commands).toEqual([])
  expect(w.seen.status.at(-1)).toContain('HEAD could not be read')
  expect(w.seen.status.at(-1)).toContain('fatal: bad object HEAD')
  expect(w.marker().state).toBe('armed')
})

test("the clear's SessionStart names why HEAD could not be read", async ($, on) => {
  const w = world(on)
  await $.classic.SessionStart({ source: 'startup' })
  w.arm({ session_id: w.id(), head: HEAD })
  w.state.id = 'the-new-session'
  w.state.gitFails['git rev-parse HEAD'] = { exitCode: 128, stderr: 'fatal: bad object HEAD' }
  await $.classic.SessionStart({ source: 'clear' })
  expect(w.seen.prompts.length).toBe(1)
  expect(w.seen.prompts[0]).toContain('HEAD could not be read')
  expect(w.seen.prompts[0]).toContain('fatal: bad object HEAD')
})

test("a git status git refuses names git's words, not its empty stdout", async ($, on) => {
  const w = world(on)
  w.state.gitFails['git status --porcelain --untracked-files=no'] = { exitCode: 128, stderr: 'fatal: index file corrupt' }
  w.arm({ session_id: w.id(), head: HEAD })
  await $.turn.complete(TURN)
  expect(w.seen.commands).toEqual([])
  expect(w.seen.status.at(-1)).toContain('git status could not be read')
  expect(w.seen.status.at(-1)).toContain('fatal: index file corrupt')
})

test('a git read that fails with nothing on stderr names its exit code', async ($, on) => {
  const w = world(on)
  w.state.gitFails['git rev-parse HEAD'] = { exitCode: 129 }
  w.arm({ session_id: w.id(), head: HEAD })
  await $.turn.complete(TURN)
  expect(w.seen.commands).toEqual([])
  expect(w.seen.status.at(-1)).toContain('HEAD could not be read')
  expect(w.seen.status.at(-1)).toContain('129')
})

test('a git read the engine rejects names the rejection', async ($, on) => {
  const w = world(on)
  w.state.gitFails['git rev-parse HEAD'] = { deny: 'git outran its 10000 ms' }
  w.arm({ session_id: w.id(), head: HEAD })
  await $.turn.complete(TURN)
  expect(w.seen.commands).toEqual([])
  expect(w.seen.status.at(-1)).toContain('HEAD could not be read')
  expect(w.seen.status.at(-1)).toContain('git outran its 10000 ms')
})

test("git's words are one line of at most 200 characters, its fatal line kept", async ($, on) => {
  // git prints `fatal:` after its warnings, so the cut keeps the end.
  const w = world(on)
  w.state.gitFails['git rev-parse HEAD'] = { exitCode: 128, stderr: `${'warning: a long preamble\n\n'.repeat(20)}fatal: bad object HEAD\n` }
  w.arm({ session_id: w.id(), head: HEAD })
  await $.turn.complete(TURN)
  const shown = w.seen.status.at(-1) ?? ''
  expect(shown.includes('\n')).toBe(false)
  expect(shown.endsWith('fatal: bad object HEAD)')).toBe(true)
  const said = shown.slice(shown.indexOf('exit 128: ') + 'exit 128: '.length, -1)
  expect(said.startsWith('...')).toBe(true)
  expect(said.length).toBe(200)
})

test('a checkout top git answers with no path is named on the log', async ($, on) => {
  const LOG = '/logs/own-clear.jsonl'
  const w = world(on, { env: { ESPALIER_OWN_CLEAR_LOG: LOG } })
  w.state.gitFails['git rev-parse --show-toplevel'] = { exitCode: 0 }
  w.arm({ session_id: w.id(), head: HEAD })
  await $.session.start({ cwd: ROOT } as any)
  expect(w.files.get(LOG) ?? '').toContain('git printed no path')
})

test("a checkout top git cannot read is named on the log, and the marker is read from the session's folder", async ($, on) => {
  const LOG = '/logs/own-clear.jsonl'
  const w = world(on, { env: { ESPALIER_OWN_CLEAR_LOG: LOG } })
  w.state.gitFails['git rev-parse --show-toplevel'] = {
    exitCode: 128, stderr: 'fatal: not a git repository (or any of the parent directories): .git',
  }
  w.arm({ session_id: w.id(), head: HEAD })
  await $.session.start({ cwd: ROOT } as any)
  expect(w.files.get(LOG) ?? '').toContain('not a git repository')
  await $.turn.complete(TURN)
  expect(w.seen.commands).toEqual(['clear'])
})
