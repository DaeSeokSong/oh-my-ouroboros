import { expect, mock, test } from 'claude-code/testing'
import { isOwnNotice } from '../hooks/band/propagate.js'

// 2026-11-02 intent/2026-11-02-no-work-in-spare-sessions.md: 첫 지시가 들어오기 전(빈 spare 세션)에는 하네스 전파 알림을 넣지 않고 받음 기록도 남기지 않는다.
const SID = '0c7530cd-4cc9-47a1-9df0-ab9103f6e70d'
const DIR = '/home/user/.claude/_usage/propagate'
const PENDING = `${DIR}/pending.jsonl`
const ACK = `${DIR}/ack/${SID}`
const ASLEEP = `${DIR}/asleep/${SID}`
const HEAD = '[하네스 변경 알림'

// 시작 시각 이후의 커밋 한 건이 대기 중이다. submits 에는 mod 가 넣은 알림과 시험이 직접 낸 글이 다 쌓인다.
function stubs(on, files: Map<string, string>, submits: any[]) {
  const clock = mock.clock(on, { now: Date.now() })
  files.set(PENDING, JSON.stringify({ ts: Math.floor(Date.now() / 1000) + 100, hash: 'abc1234', subject: 'feat: Test commit', author: '' }) + '\n')
  on('store.get', () => ({ value: undefined }))
  on('store.set', () => ({ value: undefined }))
  on('session.start', () => ({ cwd: '/work' }))
  on('command.register', () => ({ value: undefined }))
  on('session.surfaces', () => ({ value: [] }))
  on('env.get', (_$, e) => ({ value: (e.name === 'HOME' || e.key === 'HOME') ? '/home/user' : undefined }))
  on('session.id', () => ({ value: SID }))
  on('session.cwd', () => ({ value: '/work' }))
  on('fs.exists', (_$, e) => ({ value: files.has(e.path) }))
  on('fs.read', (_$, e) => {
    if (!files.has(e.path)) throw new Error('ENOENT')
    return { value: files.get(e.path) }
  })
  on('fs.write', (_$, e) => { files.set(e.path, e.content ?? e.data ?? e.text); return { value: undefined } })
  on('prompt.submit', (_$, e) => { submits.push(e); return { text: e.text } })
  return clock
}
const settle = async (clock) => { for (let i = 0; i < 20; i++) { await clock.settle(); await new Promise(r => setTimeout(r, 1)) } }
const tick = async (clock, n = 3) => { for (let i = 0; i < n; i++) { await clock.advance(3000); await settle(clock) } }
const start = async ($, clock) => { await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' }); await settle(clock) }
const notices = (submits: any[]) => submits.filter(s => String(s.text).startsWith(HEAD))
const say = async ($, clock, origin: any, text = '안녕하세요') => { await ($.prompt.submit as any)({ text, origin, wait: false }); await settle(clock) }

test('isOwnNotice: 이 플러그인 출처이거나 알림 머리로 시작하면 true, 그 밖은 false', () => {
  expect(isOwnNotice({ kind: 'plugin', name: 'harness-mod' }, '아무 글')).toBe(true)
  expect(isOwnNotice(undefined, `${HEAD} · 회신 불요] 새 커밋`)).toBe(true)
  expect(isOwnNotice({ kind: 'plugin', name: 'other' }, '아무 글')).toBe(false)
  expect(isOwnNotice({ kind: 'composer' }, '아무 글')).toBe(false)
  expect(isOwnNotice(undefined, '')).toBe(false)
})

test('첫 지시 전: 알림 0 · 받음 기록 쓰기 0', async ($, on) => {
  const files = new Map<string, string>()
  const submits: any[] = []
  const clock = stubs(on, files, submits)
  await start($, clock)
  await tick(clock)
  expect(submits.length).toBe(0)
  expect(files.has(ACK)).toBe(false)
  expect(files.get(ASLEEP)).toMatch(/^asleep\t\d+\n$/) // Stop 훅이 빈 세션을 건너뛰게 하는 표지
})

test('깨어난 뒤 첫 주기에 asleep 표지를 awake 로 덮어쓴다', async ($, on) => {
  const files = new Map<string, string>()
  const submits: any[] = []
  const clock = stubs(on, files, submits)
  await start($, clock)
  await tick(clock, 1)
  expect(files.get(ASLEEP)).toMatch(/^asleep\t/)
  await say($, clock, { kind: 'composer' })
  await tick(clock, 1)
  expect(files.get(ASLEEP)).toMatch(/^awake\t\d+\n$/)
})

test('composer 지시 뒤: 다음 주기에 알림 1건, 받음 기록이 남고 되풀이되지 않는다', async ($, on) => {
  const files = new Map<string, string>()
  const submits: any[] = []
  const clock = stubs(on, files, submits)
  await start($, clock)
  await tick(clock, 2)
  expect(notices(submits).length).toBe(0)
  await say($, clock, { kind: 'composer' })
  await tick(clock)
  expect(notices(submits).length).toBe(1)
  expect(files.get(ACK)).toContain('abc1234')
})

test('이 mod 자신의 알림 submit 만 있으면 깨어 있음으로 치지 않는다', async ($, on) => {
  const files = new Map<string, string>()
  const submits: any[] = []
  const clock = stubs(on, files, submits)
  await start($, clock)
  await say($, clock, { kind: 'plugin', name: 'harness-mod' }, `${HEAD} · 회신 불요] 하네스 저장소에 새 커밋이 생겼습니다.`)
  await say($, clock, { kind: 'plugin', name: 'harness-mod' }, '머리 없는 글')
  const before = notices(submits).length
  await tick(clock)
  expect(notices(submits).length).toBe(before)
  expect(files.has(ACK)).toBe(false)
})

test('다른 플러그인 출처 지시도 깨어 있음으로 쳐 알림 1건이 들어간다', async ($, on) => {
  const files = new Map<string, string>()
  const submits: any[] = []
  const clock = stubs(on, files, submits)
  await start($, clock)
  await say($, clock, { kind: 'plugin', name: 'other-plugin' })
  await tick(clock)
  expect(notices(submits).length).toBe(1)
})
