import { expect, mock, test } from 'claude-code/testing'
import { loginWarning, parseExpiry } from '../hooks/band/login.js'
import { buildBand } from '../hooks/band/model.js'
import { lineWidth } from '../hooks/band/width.js'
import { PALETTES } from '../hooks/band/view.js'

// 2026-11-16 intent/2026-11-16-login-expiry-band-warning.md: 로그인 만료 경보. 토큰 값은 전부 가짜다.
const DAY = 86400000
const EXP = Date.UTC(2026, 11, 13, 14, 37) // 2026-12-13 23:37 KST
const at = (leftMs: number) => loginWarning(EXP, EXP - leftMs)

test('parseExpiry: 숫자 한 줄(12~14자리)만 숫자로, 빈 값 · 문자열 · 소수 · 음수 · 자릿수 밖 · 두 줄 · 토큰 꼴은 null', () => {
  expect(parseExpiry(`${EXP}\n`)).toBe(EXP)
  expect(parseExpiry(String(EXP))).toBe(EXP)
  expect(parseExpiry('100000000000')).toBe(100000000000)   // 12자리
  expect(parseExpiry('99999999999')).toBeNull()            // 11자리
  expect(parseExpiry('100000000000000')).toBeNull()        // 15자리
  for (const bad of ['', '\n', 'abc', '1796000000000x', '1796000000.5', '-1796000000000', `${EXP}\n${EXP}`, '{"claudeAiOauth": FAKE-REFRESH', '"1796000000000"'])
    expect(parseExpiry(bad)).toBeNull()
  expect(parseExpiry(undefined)).toBeNull()
  expect(parseExpiry(null)).toBeNull()
  expect(parseExpiry(EXP as any)).toBeNull()
})

test('loginWarning 경계: D-8 없음 · 7일 정확히 D-7 노랑 · D-4 노랑 · D-3 주황 · D-2 주황 · D-1 빨강', () => {
  expect(at(7 * DAY + 1)).toBeNull()
  expect(at(8 * DAY)).toBeNull()
  expect(at(7 * DAY)).toEqual({ text: '⚠ 로그인 만료 D-7 (12-13 23:37) · claude auth login', tone: 'loginY' })
  expect(at(6.5 * DAY)?.tone).toBe('loginY')
  expect(at(3 * DAY + 1)?.text).toContain('D-4')
  expect(at(3 * DAY + 1)?.tone).toBe('loginY')
  expect(at(3 * DAY)?.text).toContain('D-3')
  expect(at(3 * DAY)?.tone).toBe('loginO')
  expect(at(2 * DAY + 1)?.tone).toBe('loginO')
  expect(at(2 * DAY)?.text).toContain('D-2')
  expect(at(2 * DAY)?.tone).toBe('loginO')
  expect(at(DAY + 1)?.text).toContain('D-2')
  expect(at(DAY)?.text).toContain('D-1')
  expect(at(DAY)?.tone).toBe('loginR')
  expect(at(1)?.text).toContain('D-1')
  expect(at(1)?.tone).toBe('loginR')
})

test('loginWarning: 만료 뒤(정각 포함)는 «로그인 만료됨» 빨강, 값이 없거나 숫자가 아니면 null', () => {
  const gone = { text: '⚠ 로그인 만료됨 (12-13 23:37) · claude auth login', tone: 'loginR' }
  expect(at(0)).toEqual(gone)
  expect(at(-DAY)).toEqual(gone)
  expect(loginWarning(null, EXP)).toBeNull()
  expect(loginWarning(undefined, EXP)).toBeNull()
  expect(loginWarning('1796000000000' as any, EXP)).toBeNull()
  expect(loginWarning(NaN, EXP)).toBeNull()
})

test('loginWarning: 표기 시각은 KST 고정(UTC 날짜가 달라지는 15:00 UTC 이후도 다음 날로 적는다)', () => {
  const a = Date.UTC(2026, 0, 1, 15, 5), b = Date.UTC(2026, 11, 31, 14, 59)
  expect(loginWarning(a, a - DAY)?.text).toContain('(01-02 00:05)')
  expect(loginWarning(b, b - DAY)?.text).toContain('(12-31 23:59)')
})

test('색: 세 톤이 라이트 · 다크 팔레트에 모두 있다', () => {
  for (const p of [PALETTES.dark, PALETTES.light]) for (const k of ['loginY', 'loginO', 'loginR']) expect(p[k]).toMatch(/^#[0-9A-Fa-f]{6}$/)
})

const base = { work: null, server: null, selfSid: 'x', expanded: false }
const warn = { text: '⚠ 로그인 만료 D-3 (12-13 23:37) · claude auth login', tone: 'loginO' }

test('buildBand(접힘): login 이 있으면 줄이 하나 늘고 54칸에서도 폭 안에서 잘리며, 없으면 종전과 같다', () => {
  expect(buildBand({ ...base, columns: 200 }).length).toBe(2)
  const rows = buildBand({ ...base, columns: 200, login: warn })
  expect(rows.length).toBe(3)
  expect(rows[2]).toEqual([{ text: warn.text, tone: 'loginO' }])
  const narrow = buildBand({ ...base, columns: 54, login: warn })[2]
  expect(lineWidth(narrow)).toBeLessThanOrEqual(50)
  expect(narrow[0].text.endsWith('…')).toBe(true)
  expect(narrow[0].tone).toBe('loginO')
})

test('buildBand(펼침): 경보는 고정 첫 줄 왼쪽 배지 뒤에 놓이고 줄 수는 그대로이며, 좁으면 잘리고 아주 좁으면 생략한다', () => {
  const ex = { ...base, expanded: true }
  const plain = buildBand({ ...ex, columns: 200 })
  const rows = buildBand({ ...ex, columns: 200, login: warn })
  expect(rows.length).toBe(plain.length)
  expect(rows[0].find(s => s.tone === 'loginO')?.text).toBe(warn.text)
  expect(rows[0][0].text).toBe(' 작업 ')
  const mid = buildBand({ ...ex, columns: 80, login: warn })
  const seg = mid[0].find(s => s.tone === 'loginO')
  expect(seg?.text.endsWith('…')).toBe(true)
  expect(mid.length).toBe(buildBand({ ...ex, columns: 80 }).length)
  for (const columns of [54, 44, 30]) {
    const r = buildBand({ ...ex, columns, login: warn })
    expect(r.length).toBe(buildBand({ ...ex, columns }).length)
    expect(lineWidth(r[0])).toBeLessThanOrEqual(lineWidth(buildBand({ ...ex, columns })[0]) + 1)
  }
})

// ---- register.js 배선: _usage/login-expiry 만 읽고(자격 증명 파일은 열지 않음), 10분마다 다시 읽는다 ----
const SID = '0c7530cd-4cc9-47a1-9df0-ab9103f6e70d'
const FILE = '/home/user/.claude/_usage/login-expiry'
const SITE = {
  plugin: 'harness-mod', component: 'AbovePrompt', requestId: 'band', viewport: { columns: 200, rows: 40 },
  props: { hasSurvey: false, isWorking: false, maxRows: 30, bodyColumns: 200, scroll: { offset: 0, bodyRows: 29 }, view: {} },
} as const
function stubs(on, files: Map<string, string>, reads: string[]) {
  const clock = mock.clock(on, { now: Date.now() })
  on('store.get', () => ({ value: undefined }))
  on('store.set', () => ({ value: undefined }))
  on('session.start', () => ({ cwd: '/work' }))
  on('command.register', () => ({ value: undefined }))
  on('session.surfaces', () => ({ value: ['terminal'] }))
  on('env.get', (_$, e) => ({ value: (e.name === 'HOME' || e.key === 'HOME') ? '/home/user' : undefined }))
  on('session.id', () => ({ value: SID }))
  on('session.cwd', () => ({ value: '/work' }))
  on('process.run', () => ({ value: { exitCode: 1, stdout: '', stderr: '' } }))
  on('fs.read', (_$, e) => { reads.push(e.path); if (!files.has(e.path)) throw new Error('ENOENT'); return { value: files.get(e.path) } })
  on('fs.write', () => ({ value: undefined }))
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['drawn by Claude Code'] }))
  return clock
}
const settle = async (clock) => { for (let i = 0; i < 20; i++) { await clock.settle(); await new Promise(r => setTimeout(r, 1)) } }
const begin = async ($, clock) => { await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' }); await settle(clock) }

test('배선: 파일이 3일 이하면 경보가 그려지고, 재로그인으로 값이 늦춰지면 10분 안에 사라지며, 읽는 파일은 login-expiry 뿐이다', async ($, on) => {
  const soon = Date.now() + 2.5 * DAY   // register.js 는 Date.now() 를 쓰므로 실제 지금 기준 D-3
  const files = new Map<string, string>([[FILE, `${soon}\n`]])
  const reads: string[] = []
  const clock = stubs(on, files, reads)
  await begin($, clock)
  const ui = await $.ui.mount({ ...SITE, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /로그인 만료 D-3/ })).toBeDefined()
  files.set(FILE, `${soon + 30 * DAY}\n`)
  await clock.advance(600000)
  await settle(clock)
  expect(await ui.find({ type: 'Text', text: /로그인 만료/ })).toBeUndefined()
  expect(reads.some(p => p.includes('credentials'))).toBe(false)
  await ui.unmount()
})

for (const [name, content] of [['파일 없음', undefined], ['글자', 'garbage\n'], ['빈 파일', '']] as const) {
  test(`배선: ${name}이면 조용하다`, async ($, on) => {
    const files = new Map<string, string>(content === undefined ? [] : [[FILE, content]])
    const clock = stubs(on, files, [])
    await begin($, clock)
    const ui = await $.ui.mount({ ...SITE, surface: 'terminal' })
    expect(await ui.find({ type: 'Text', text: /로그인 만료/ })).toBeUndefined()
    await ui.unmount()
  })
}
