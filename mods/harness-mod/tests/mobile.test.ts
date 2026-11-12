import { expect, mock, test } from 'claude-code/testing'

// 2026-11-03 intent/2026-11-03-band-button-chips-mobile-toggle.md: 띠의 «📱 모바일 on/off» 버튼. 글자는 decision-popup 이 쓰는 세션별 상태 파일에서 읽고,
// 누르면 `/mobile-mode`(인자 없음 = 뒤집기, `/mobile` 은 내장 명령이라 못 쓴다)를 부른 뒤 파일을 다시 읽는다. 시험은 가짜 fs 라 실제 ~/.claude 에는 쓰지 않는다.
const SID = '0c7530cd-4cc9-47a1-9df0-ab9103f6e70d'
const FILE = `/home/user/.claude/_usage/decision-popup/mobile/${SID}`
const SITE = {
  plugin: 'harness-mod',
  component: 'AbovePrompt',
  requestId: 'band',
  viewport: { columns: 200, rows: 40 },
  props: { hasSurvey: false, isWorking: false, maxRows: 30, bodyColumns: 200, scroll: { offset: 0, bodyRows: 29 }, view: {} },
} as const

// decision-popup 의 /mobile-mode 를 흉내 내는 바닥 훅: 인자 없음 = 뒤집기, on/off = 그 상태. 파일에 on/off 한 줄을 쓴다(decision-popup 이 하는 일).
function stubs(on, files: Map<string, string>, runs: any[], sid = SID) {
  const clock = mock.clock(on, { now: Date.now() })
  on('store.get', () => ({ value: undefined }))
  on('store.set', () => ({ value: undefined }))
  on('session.start', () => ({ cwd: '/work' }))
  on('command.register', () => ({ value: undefined }))
  on('session.surfaces', () => ({ value: ['terminal'] }))
  on('env.get', (_$, e) => ({ value: (e.name === 'HOME' || e.key === 'HOME') ? '/home/user' : undefined }))
  on('session.id', () => ({ value: sid }))
  on('session.cwd', () => ({ value: '/work' }))
  on('process.run', () => ({ value: { exitCode: 1, stdout: '', stderr: '' } }))
  on('fs.read', (_$, e) => {
    if (!files.has(e.path)) throw new Error('ENOENT')
    return { value: files.get(e.path) }
  })
  on('fs.write', (_$, e) => { files.set(e.path, e.content ?? e.data ?? e.text); return { value: undefined } })
  on('command.run', (_$, e) => {
    if (e.command !== 'mobile-mode') return {}
    runs.push(e)
    const arg = String(e.args ?? '').trim()
    const cur = (files.get(FILE) ?? 'off\n').trim() === 'on'
    files.set(FILE, (arg === 'on' ? true : arg === 'off' ? false : !cur) ? 'on\n' : 'off\n')
    return {}
  })
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['drawn by Claude Code'] }))
  return clock
}
const settle = async (clock) => { for (let i = 0; i < 20; i++) { await clock.settle(); await new Promise(r => setTimeout(r, 1)) } }
const start = async ($, clock) => { await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' }); await settle(clock) }
const label = async (ui, key: string) => (await ui.find({ key })).props.label

test('band-mobile 버튼: 파일이 없으면 «📱 모바일 off», 눌리면 /mobile-mode(인자 없음)을 부르고 파일을 다시 읽어 on ↔ off 로 바뀐다', async ($, on) => {
  const files = new Map<string, string>()
  const runs: any[] = []
  const clock = stubs(on, files, runs)
  await start($, clock)
  const ui = await $.ui.mount({ ...SITE, surface: 'terminal' })
  expect(await label(ui, 'band-mobile')).toBe('📱 모바일 off')
  await ui.press({ key: 'band-mobile' })
  await settle(clock)
  expect(runs.length).toBe(1)
  expect(String(runs[0].args ?? '')).toBe('')   // 인자 없음 = 뒤집기
  expect(await label(ui, 'band-mobile')).toBe('📱 모바일 on')
  await ui.press({ key: 'band-mobile' })
  await settle(clock)
  expect(runs.length).toBe(2)
  expect(await label(ui, 'band-mobile')).toBe('📱 모바일 off')
  expect([...files.keys()].filter(k => k.includes('/decision-popup/'))).toEqual([FILE])   // 이 세션 파일만 만진다
  await ui.unmount()
})

test('band-mobile 버튼: 시작할 때 파일 값을 읽고, 사람 글로 바뀐 파일도 다음 갱신 주기에 반영하며, 이상한 값은 off', async ($, on) => {
  const files = new Map<string, string>([[FILE, 'on\n']])
  const clock = stubs(on, files, [])
  await start($, clock)
  const ui = await $.ui.mount({ ...SITE, surface: 'terminal' })
  expect(await label(ui, 'band-mobile')).toBe('📱 모바일 on')
  files.set(FILE, 'off\n')   // decision-popup 이 사람 글(모바일 해제)로 파일을 갱신
  clock.advance(5000)
  await settle(clock)
  expect(await label(ui, 'band-mobile')).toBe('📱 모바일 off')
  files.set(FILE, 'maybe\n')
  clock.advance(5000)
  await settle(clock)
  expect(await label(ui, 'band-mobile')).toBe('📱 모바일 off')
  await ui.unmount()
})

test('band-mobile 버튼: 이상한 세션 id 면 파일을 읽지 않아 off 이고, 눌려도 다른 파일을 만들지 않는다', async ($, on) => {
  const files = new Map<string, string>([['/home/user/.claude/_usage/decision-popup/mobile/../evil', 'on\n']])
  const clock = stubs(on, files, [], '../evil')
  await start($, clock)
  const ui = await $.ui.mount({ ...SITE, surface: 'terminal' })
  expect(await label(ui, 'band-mobile')).toBe('📱 모바일 off')
  await ui.unmount()
})
