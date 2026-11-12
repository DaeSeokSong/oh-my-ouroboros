import { expect, mock, test } from 'claude-code/testing'
import { buildBand } from '../hooks/band/model.js'
import { lineWidth } from '../hooks/band/width.js'

// 2026-11-02 intent/2026-11-02-news-line-per-session.md: /news 명령 · 띠 «📰 뉴스» 버튼 · 세션별 상태 파일(~/.claudenews/view.<세션 id>).
const SID = '0c7530cd-4cc9-47a1-9df0-ab9103f6e70d'
const FILE = `/home/user/.claudenews/view.${SID}`
const SITE = {
  plugin: 'harness-mod',
  component: 'AbovePrompt',
  requestId: 'band',
  viewport: { columns: 200, rows: 40 },
  props: { hasSurvey: false, isWorking: false, maxRows: 30, bodyColumns: 200, scroll: { offset: 0, bodyRows: 29 }, view: {} },
} as const

function stubs(on, files: Map<string, string>, registered: any[] = [], sid = SID) {
  const clock = mock.clock(on, { now: Date.now() })
  on('store.get', () => ({ value: undefined }))
  on('store.set', () => ({ value: undefined }))
  on('session.start', () => ({ cwd: '/work' }))
  on('command.register', (_$, e) => { registered.push(e); return { value: undefined } })
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
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['drawn by Claude Code'] }))
  return clock
}
const settle = async (clock) => { for (let i = 0; i < 20; i++) { await clock.settle(); await new Promise(r => setTimeout(r, 1)) } }
const start = async ($, clock) => { await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' }); await settle(clock) }
const label = async (ui, key: string) => (await ui.find({ key })).props.label

test('buildBand: news 글자가 있으면 펼친 줄에 band-news 버튼이 크게 버튼 앞에 놓이고, 비어 있으면 종전과 같다', () => {
  const base = { work: null, server: null, selfSid: SID, columns: 200, expanded: true }
  const keys = rows => rows[0].filter(s => s.button && s.key).map(s => s.key)
  expect(keys(buildBand({ ...base, news: '📰 뉴스 작게' }))).toEqual(['band-news', 'band-mobile', 'band-mask', 'band-big', 'band-toggle'])   // 2026-11-03: 뉴스 · 모바일 · 마스킹 · 크게 · 접기
  expect(keys(buildBand({ ...base }))).toEqual(['band-mobile', 'band-mask', 'band-big', 'band-toggle'])
})

test('buildBand(접힘): 오른쪽 band-news-toggle 글자는 켬(크게·작게)이면 «📰 on», 끔이면 «📰 off»(칩 여백 포함)이고 36칸까지 남으며, 더 좁으면 상세만 남는다', () => {
  const lead = (newsState: string, columns = 200) => buildBand({ work: null, server: null, selfSid: SID, columns, expanded: false, newsState })[0].find(s => s.key === 'band-news-toggle')
  expect(lead('max').text).toBe(' 📰 on ')
  expect(lead('min').text).toBe(' 📰 on ')
  expect(lead('off').text).toBe(' 📰 off ')
  for (const columns of [200, 80, 40, 37, 36, 30]) {
    for (const st of ['max', 'off']) {
      const row = buildBand({ work: null, server: null, selfSid: SID, columns, expanded: false, newsState: st })[0]
      const keys = row.filter(s => s.button && s.key).map(s => s.key)
      expect(keys[keys.length - 1]).toBe('band-toggle')   // 상세는 가장 좁은 폭(30)에서도 남는다
      expect(lineWidth(row)).toBeLessThanOrEqual(columns - 4)
      if (columns >= 36) {
        expect(keys[0]).toBe('band-news-toggle')
        expect(row.findIndex(s => s.key === 'band-news-toggle')).toBeGreaterThan(0)   // 첫 칸이 아니라 오른쪽 무리
      } else {
        expect(keys).toEqual(['band-toggle'])   // 뉴스는 모바일 · 마스킹 다음으로 빠진다
      }
    }
  }
  expect(buildBand({ work: null, server: null, selfSid: SID, columns: 200, expanded: true })[0].some(s => s.key === 'band-news-toggle')).toBe(false)
})

test('band-news-toggle 버튼: 접힌 띠에서 max → off → max, min → off, 이 세션 파일에만 쓴다', async ($, on) => {
  const files = new Map<string, string>()
  const clock = stubs(on, files)
  await start($, clock)
  const ui = await $.ui.mount({ ...SITE, surface: 'terminal' })
  expect(await label(ui, 'band-news-toggle')).toBe('📰 on')
  await ui.press({ key: 'band-news-toggle' })
  await settle(clock)
  expect(await label(ui, 'band-news-toggle')).toBe('📰 off')
  expect(files.get(FILE)).toBe('off\n')
  await ui.press({ key: 'band-news-toggle' })
  await settle(clock)
  expect(await label(ui, 'band-news-toggle')).toBe('📰 on')
  expect(files.get(FILE)).toBe('max\n')
  files.set(FILE, 'min\n')   // 파일을 직접 작게로 고쳐도 반영한 뒤 끈다
  await ui.press({ key: 'band-news-toggle' })
  await settle(clock)
  expect(files.get(FILE)).toBe('off\n')
  expect([...files.keys()].filter(k => k.includes('/.claudenews/'))).toEqual([FILE])   // 다른 mod 파일(asleep 등)은 세지 않는다
  await ui.unmount()
})

test('/news: 등록되고 인자 없으면 크게 → 작게 → 끔 → 크게 로 돌며 이 세션 파일에만 쓴다', async ($, on) => {
  const files = new Map<string, string>()
  const registered: any[] = []
  const clock = stubs(on, files, registered)
  await start($, clock)
  expect(registered.some(r => r.name === 'news' && r.description === '이 세션의 뉴스 줄을 크게 · 작게 · 끔으로 바꿉니다(인자 없으면 차례로)')).toBe(true)
  const seq: string[] = []
  for (let i = 0; i < 4; i++) {
    await $.command.run({ command: 'news' })
    await settle(clock)
    seq.push(files.get(FILE) as string)
  }
  expect(seq).toEqual(['min\n', 'off\n', 'max\n', 'min\n'])
  expect([...files.keys()].filter(k => !k.includes('/_usage/propagate/asleep/'))).toEqual([FILE]) // 잠든 표지는 전파 쪽 파일이라 제외
})

test('/news 인자: 끄기 · off · 켜기 · on · 크게 · max · 작게 · min 을 그 상태로 쓴다', async ($, on) => {
  const files = new Map<string, string>()
  const clock = stubs(on, files)
  await start($, clock)
  const cases: [string, string][] = [['끄기', 'off'], ['켜기', 'max'], ['작게', 'min'], ['크게', 'max'], ['off', 'off'], ['on', 'max'], ['min', 'min'], ['max', 'max']]
  for (const [arg, want] of cases) {
    await $.command.run({ command: 'news', args: arg })
    await settle(clock)
    expect(files.get(FILE)).toBe(want + '\n')
  }
})

test('/news: 이상한 세션 id 면 파일을 쓰지 않는다', async ($, on) => {
  const files = new Map<string, string>()
  const clock = stubs(on, files, [], '../evil')
  await start($, clock)
  await $.command.run({ command: 'news', args: 'off' })
  await settle(clock)
  expect(files.size).toBe(0)
})

test('band-news 버튼: 펼친 띠에서 눌릴 때마다 글자와 파일이 순환하고, 시작할 때 파일 값을 읽는다', async ($, on) => {
  const files = new Map<string, string>([[FILE, 'off\n']])
  const clock = stubs(on, files)
  await start($, clock)
  const ui = await $.ui.mount({ ...SITE, surface: 'terminal' })
  await ui.press({ key: 'band-toggle' })
  await settle(clock)
  expect(await label(ui, 'band-news')).toBe('📰 뉴스 끔')
  await ui.press({ key: 'band-news' })
  await settle(clock)
  expect(await label(ui, 'band-news')).toBe('📰 뉴스 크게')
  expect(files.get(FILE)).toBe('max\n')
  await ui.press({ key: 'band-news' })
  await settle(clock)
  expect(await label(ui, 'band-news')).toBe('📰 뉴스 작게')
  expect(files.get(FILE)).toBe('min\n')
  await ui.press({ key: 'band-toggle' })
  await ui.unmount()
})
