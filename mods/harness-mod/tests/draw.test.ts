import { expect, mock, test } from 'claude-code/testing'
import { treeRows } from '../hooks/band/view.js'

// 띠를 실제 엔진 검증으로 그려 본다($.ui.mount 는 트리가 그 앱에서 유효한지까지 검사한다).
// 2026-10-15 실사고: Text 에 flexShrink 를 넣어 세션에서 «Text prop "flexShrink" is not allowed» 로 거부됐는데
// 순수 함수 시험은 이를 못 잡았다. 이 시험이 그 자리를 막는다.
const SID = '0c7530cd-4cc9-47a1-9df0-ab9103f6e70d'
const SITE = {
  plugin: 'harness-mod',
  component: 'AbovePrompt',
  requestId: 'band',
  viewport: { columns: 200, rows: 30 },   // 펼친 보기는 좌우 반으로 갈라(개정 13) 왼쪽 반이 열의 절반이라 판 줄이 잘리지 않으려면 넓은 열이 필요하다
  props: { hasSurvey: false, isWorking: false, maxRows: 12, bodyColumns: 200, scroll: { offset: 0, bodyRows: 11 }, view: {} },   // bodyRows = maxRows − «n more» 줄
} as const

const WORK = { codex: [{ model: 'gpt-6.1-sol', effort: 'xhigh' }], grok: [], train: { running: ['exp-a1'], ended: [] } }
const serverJson = () => JSON.stringify({
  ts: Date.now() / 1000,
  gpus: [{ i: 0, util: 0, used: 14, total: 46068 }, { i: 3, util: 96, used: 26419, total: 81559 }],
  mem: { total: 503 * 2 ** 30, avail: 212 * 2 ** 30 },
  disk: { total: 879 * 2 ** 30, avail: 121 * 2 ** 30 },
  sessions: [{ sid: SID, name: '[Harness] Manager', status: 'busy', job_state: 'working', job_detail: '띠 와쳐 표시 반영 확인' },
    { sid: 'b', name: '[PRJ] Manager', status: 'shell', job_state: 'needs_input', job_detail: 'run_exp.py 추론 결과 확인' },
    { sid: 'c', name: '[PRJ] 2.0.0', status: 'idle', job_state: null, job_detail: null }],
  train: [{ gpu: 3, name: 'exp-mtl-14t-r72-1t', max_epochs: 60, done: 17, metric: 'val_gated_tri_mean', last: true, watcher: true,
    ckpts: [{ epoch: 4, value: -0.2779 }, { epoch: 14, value: -0.2247 }] }],
})

function stubs(on, home: string | null = '/home/user', opts: { server?: () => string, ran?: string[][], work?: object } = {}) {
  const clock = mock.clock(on, { now: Date.now() })
  on('session.start', () => ({ cwd: '/work' }))
  on('command.register', () => ({ value: undefined }))
  on('session.surfaces', () => ({ value: ['terminal'] }))
  on('env.get', ($, e) => ({ value: (e.name === 'HOME' || e.key === 'HOME') ? (home ?? undefined) : undefined }))
  on('session.id', () => ({ value: SID }))
  on('session.cwd', () => ({ value: '/work' }))
  on('process.run', ($, e) => {
    if (opts.ran) opts.ran.push(e.argv.map(String))
    return { value: e.argv.some(a => String(a).endsWith('band_work_collect.py'))
      ? { exitCode: 0, stdout: JSON.stringify(opts.work || WORK), stderr: '' }
      : { exitCode: 0, stdout: '', stderr: '' } }
  })
  on('fs.read', ($, e) => ({ value: e.path.endsWith('server.json') ? (opts.server || serverJson)() : '' }))
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['drawn by Claude Code'] }))
  return clock
}

const settle = async (clock) => {
  for (let i = 0; i < 20; i++) { await clock.settle(); await new Promise(r => setTimeout(r, 1)) }
}

test('띠가 터미널·Desktop 두 앱에서 엔진 검증을 통과해 그려진다(펼침 포함)', async ($, on) => {
  const clock = stubs(on)
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  await settle(clock)
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...SITE, surface })
    expect(await ui.find({ type: 'Text', text: '작업' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: '작업1' })).toBeDefined()   // 접힌 띠의 Codex·Grok 호출은 개수만(개정 13)
    expect(await ui.find({ type: 'Text', text: /121\/879G|121G/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: ' │ ' })).toBeDefined() // 칸 사이 구분선
    expect(await ui.find({ type: 'Text', text: 'GPU3' })).toBeDefined()   // 접힌 띠의 GPU 별 학습 칸(판 이름 없음)
    expect(await ui.find({ type: 'Text', text: ' 1' })).toBeDefined()     // 그 GPU 에서 도는 판 수(개정 15)
    expect(await ui.find({ type: 'Text', text: /17\/60/ })).toBeUndefined()   // 에폭은 접힌 띠에 없다
    expect(await ui.find({ type: 'Text', text: /◉/ })).toBeDefined()        // 접힌 띠의 와쳐 표시
    expect(await ui.find({ type: 'Text', text: /세션/ })).toBeDefined()      // 세션 칸은 작업 줄
    await ui.press({ key: 'band-toggle' })
    expect((await ui.find({ key: 'band-toggle' })).props.label).toBe('접기 ▾')
    expect(await ui.find({ type: 'Text', text: '와쳐' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^작업 중\s*$/ })).toBeDefined()   // 세션별 작업 상태(표의 상태 열, 같은 폭으로 채움)
    expect(await ui.find({ type: 'Text', text: /^입력 대기\s*$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^이름\s*$/ })).toBeDefined()       // 세션 표 머리 줄(개정 21)
    expect(await ui.find({ type: 'Text', text: /run_exp\.py 추론 결과 확인/ })).toBeDefined()   // 세션별 현재 활동 한 줄
    expect(await ui.find({ type: 'Text', text: /26\/80G/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: 'r72-1t' })).toBeDefined()   // 펼친 보기의 판 짧은 이름
    expect(await ui.find({ type: 'Text', text: 'last' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /17\/60/ })).toBeDefined()   // 펼친 보기의 판 줄에만 끝낸 에폭 / 최대 에폭
    expect(await ui.find({ type: 'Text', text: /val_gated_tri_mean/ })).toBeUndefined()   // 지표·체크포인트는 펼친 보기에서 빠졌다(개정 15)
    expect(await ui.find({ type: 'Text', text: /e14 -0\.2247/ })).toBeUndefined()
    await ui.press({ key: 'band-toggle' })
    await ui.unmount()
  }
})

// 개정 20(2026-10-23 사용자 결정): 펼친 보기의 높이 조절 줄 · 크게 버튼 · 세션 숨김/제거 버튼이 엔진 검증을 통과하고 동작한다.
test('펼친 보기: 높이 조절 줄·크게 버튼이 그려지고, 세션 숨김·되돌리기·제거(확정 뒤 claude rm <잡 id>)가 동작한다', async ($, on) => {
  const ran: string[][] = []
  const withZ = () => {
    const base = JSON.parse(serverJson())
    base.sessions.push({ sid: 'z', name: '9e0b4934', status: 'idle', job: '9e0b4934', job_state: null, job_detail: null })
    return JSON.stringify(base)
  }
  const clock = stubs(on, '/home/user', { server: withZ, ran })
  mock.store(on)
  on('ui.toast', () => ({ value: undefined }))
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  await settle(clock)
  const ui = await $.ui.mount({ ...SITE, surface: 'terminal', props: { ...SITE.props, maxRows: 20 } })
  await ui.press({ key: 'band-toggle' })
  expect(await ui.find({ key: 'band-big' })).toBeDefined()                       // 크게 버튼
  expect(await ui.find({ key: 'band-height' })).toBeDefined()                    // 높이 조절 줄(Client)
  const ABC = /^\[PRJ\] Manager\s*$/   // 표의 이름 열은 같은 폭으로 채운다(개정 21)
  expect(await ui.find({ type: 'Text', text: ABC })).toBeDefined()
  await ui.press({ key: 'band-act-hide-b' })
  await settle(clock)
  expect(await ui.find({ type: 'Text', text: ABC })).toBeUndefined()  // 숨김
  expect(await ui.find({ type: 'Text', text: '숨긴 세션 1' })).toBeDefined()
  await ui.press({ key: 'band-act-unhide-all' })
  await settle(clock)
  expect(await ui.find({ type: 'Text', text: ABC })).toBeDefined()    // 되돌리기
  expect(await ui.find({ key: `band-act-rm-${SID}` })).toBeUndefined()            // 본인은 제거 버튼 없음
  await ui.press({ key: 'band-act-rm-z' })
  expect(await ui.find({ type: 'Text', text: '제거할까요?' })).toBeDefined()
  expect(ran.some(a => a.includes('rm'))).toBe(false)                              // 확정 전에는 실행하지 않는다
  await ui.press({ key: 'band-act-rmok-z' })
  await settle(clock)
  expect(ran.some(a => a.join(' ') === 'timeout 20 claude rm 9e0b4934')).toBe(true)
  await ui.unmount()
})

test('높이 조절 줄의 메시지: ↑ 높이 늘리기 · PgDn 넘기기에도 첫 줄(접기)이 남고, Home 은 자동, 끌기는 최소 4줄', async ($, on) => {
  const many = () => {
    const base = JSON.parse(serverJson())
    for (let i = 0; i < 14; i++) base.sessions.push({ sid: 'x' + i, name: `세션${i}`, status: 'idle', job: null, job_state: null, job_detail: null })
    return JSON.stringify(base)
  }
  const clock = stubs(on, '/home/user', { server: many })
  mock.store(on)
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  await settle(clock)
  const ui = await $.ui.mount({ ...SITE, surface: 'terminal', props: { ...SITE.props, maxRows: 12 } })
  await ui.press({ key: 'band-toggle' })
  const label = async () => String((await ui.find({ key: 'band-height' })).props.props.label)
  expect(await label()).toContain('높이 자동')
  await ui.post({ height: 8 }, { in: 'band-height' })
  await settle(clock)
  expect(await label()).toContain('높이 8줄')
  await ui.post({ nudge: 2 }, { in: 'band-height' })
  await settle(clock)
  expect(await label()).toContain('높이 10줄')
  await ui.post({ nudge: 40 }, { in: 'band-height' })
  await settle(clock)
  expect(await label()).toContain('높이 10줄')                                 // 개정 25: 넘칠 때는 엔진 창 bodyRows 11 − 엔진 그림 1줄 = 10 으로 자름
  await ui.post({ height: -5 }, { in: 'band-height' })
  await settle(clock)
  expect(await label()).toContain('높이 4줄')                                  // 끌기로는 자동이 되지 않는다
  await ui.post({ scroll: 1 }, { in: 'band-height' })
  await settle(clock)
  expect(await label()).toMatch(/스크롤 3~/)                                   // 창 2줄씩 넘김(높이 4 = 조절 줄 + 첫 줄 + 창 2)
  expect((await ui.find({ key: 'band-toggle' })).props.label).toBe('접기 ▾')   // 넘겨도 접기는 그대로
  await ui.post({ auto: true }, { in: 'band-height' })
  await settle(clock)
  expect(await label()).toContain('높이 자동')
  await ui.unmount()
})

// 개정 21(2026-10-23 사용자 지시 «팝업창이 아니라 해당 세션의 전체 크기를 차지하도록»): 창을 열지 않고 띠 높이를 이 세션 최대로.
test('크게: 크게 버튼은 창을 열지 않고 띠를 최대 높이로, 작게는 원래 높이로 돌아가며 전체 화면 방식이면 라벨에 적는다', async ($, on) => {
  const clock = stubs(on)
  mock.store(on)
  const opened: any[] = []
  on('ui.open', ($, e) => { opened.push(e); return { value: { isPlaced: true } } })
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  await settle(clock)
  const band = await $.ui.mount({ ...SITE, surface: 'terminal', props: { ...SITE.props, maxRows: 20, scroll: { offset: 0, bodyRows: 19 } } })
  await band.press({ key: 'band-toggle' })
  const label = async () => String((await band.find({ key: 'band-height' })).props.props.label)
  await band.post({ height: 8 }, { in: 'band-height' })
  await settle(clock)
  expect(await label()).toContain('높이 8줄')
  expect((await band.find({ key: 'band-big' })).props.label).toBe('크게 ⇱')
  await band.press({ key: 'band-big' })
  await settle(clock)
  expect(opened.length).toBe(0)                                                  // 창을 열지 않는다
  expect(await label()).toContain('높이 최대 19줄 · 상한 19줄')                  // 개정 23: maxRows 20 − 엔진 그림 1줄
  expect((await band.find({ key: 'band-big' })).props.label).toBe('작게 ⇲')
  await band.post({ nudge: 2 }, { in: 'band-height' })                         // 크게 상태에서 ↑ 는 크게를 유지(qa 2026-10-23)
  await settle(clock)
  expect((await band.find({ key: 'band-big' })).props.label).toBe('작게 ⇲')
  await band.press({ key: 'band-big' })
  await settle(clock)
  expect(await label()).toContain('높이 8줄')                                    // 크게 전 높이로
  await band.press({ key: 'band-big' })
  await band.press({ key: 'band-big' })
  await band.press({ key: 'band-big' })
  await band.press({ key: 'band-big' })
  await settle(clock)
  expect(await label()).toContain('높이 8줄')                                    // 연타해도 돌아갈 높이는 그대로
  expect((await band.find({ key: 'band-big' })).props.label).toBe('크게 ⇱')
  await band.unmount()
  const full = await $.ui.mount({ ...SITE, surface: 'terminal', viewport: { ...SITE.viewport, isFullscreen: true }, props: { ...SITE.props, maxRows: 5, scroll: { offset: 0, bodyRows: 4 } } } as never)
  expect(String((await full.find({ key: 'band-height' })).props.props.label)).toContain('상한 3줄(세션 창의 절반)')   // 개정 24: 괄호는 짧게 · 개정 25: 넘칠 때 상한은 bodyRows 4 − 엔진 그림 1줄
  await full.unmount()
})

// 개정 22(2026-10-23 사용자 지시 «할일 목록도 접었다 폈다 할 수 있게»): 띠의 할 일 묶음 [펼치기]·[접기] 가 엔진 검증을 통과하고 동작한다.
test('할 일 묶음: 접힌 띠에 개수, 펼친 보기의 [펼치기] 를 누르면 진행·남은 항목이 보이고 [접기] 로 다시 접힌다', async ($, on) => {
  const work = { ...WORK, todos: { done: 32, doing: 2, open: 2, items: [{ state: 'doing', subject: '스크래치 스캔' }, { state: 'open', subject: 'zip 여부 묻기' }] } }
  const clock = stubs(on, '/home/user', { work })
  mock.store(on)
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  await settle(clock)
  const ui = await $.ui.mount({ ...SITE, surface: 'terminal', props: { ...SITE.props, maxRows: 20 } })
  expect(await ui.find({ type: 'Text', text: '진행' })).toBeDefined()               // 접힌 띠의 개수 칸(개정 23: 기호 대신 글자)
  await ui.press({ key: 'band-toggle' })
  expect(await ui.find({ type: 'Text', text: '스크래치 스캔' })).toBeUndefined()
  await ui.press({ key: 'band-act-todos-toggle' })
  await settle(clock)
  expect(await ui.find({ type: 'Text', text: '스크래치 스캔' })).toBeDefined()
  expect((await ui.find({ key: 'band-act-todos-toggle' })).props.label).toBe('[접기]')
  await ui.press({ key: 'band-act-todos-toggle' })
  await settle(clock)
  expect(await ui.find({ type: 'Text', text: '스크래치 스캔' })).toBeUndefined()
  await ui.unmount()
})

// 개정 25(2026-10-23 «아직도 스크롤이 안 된다», 진단 scroll.n = 0): 띠가 칸을 꽉 채우고 넘치면 트리를 칸보다 한 줄 크게 만들어 엔진이 넘김 신호를 보내게 하고,
// 띠의 ui.scroll 훅이 엔진 창 대신 띠 안 내용을 넘긴다. 시험 도구에는 휠이 없고 $.ui.scroll 은 화면 배치가 없어 넘김 위치를 못 잰다.
// 그래서 «그린 트리가 엔진 칸(maxRows)보다 크다»(엔진 문서상 휠 신호 조건)와 «띠 안 넘김에도 첫 줄·높이 줄이 남는다» 를 확인한다.
test('넘김: 띠가 칸을 꽉 채워 넘치면 트리가 엔진 칸보다 한 줄 크고, 띠 안 내용을 넘겨도 첫 줄·높이 줄은 남는다', async ($, on) => {
  const many = () => {
    const base = JSON.parse(serverJson())
    for (let i = 0; i < 14; i++) base.sessions.push({ sid: 'x' + i, name: `세션${i}`, status: 'idle', job: null, job_state: null, job_detail: null })
    return JSON.stringify(base)
  }
  const clock = stubs(on, '/home/user', { server: many })
  mock.store(on)
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  await settle(clock)
  const ui = await $.ui.mount({ ...SITE, surface: 'terminal', props: { ...SITE.props, maxRows: 12, scroll: { offset: 0, bodyRows: 11 } } })
  await ui.press({ key: 'band-toggle' })
  const label = async () => String((await ui.find({ key: 'band-height' })).props.props.label)
  expect(await label()).toMatch(/스크롤 1~/)
  expect(treeRows(await ui.drawn())).toBe(14)                                     // maxRows 12 + 2(다른 그림 어림이 한 줄 넘쳐도 maxRows 보다 크게): 엔진이 넘김 대상으로 본다
  const top = await ui.drawn()
  expect(JSON.stringify(top.children?.[0] ?? top.props?.children?.[0])).toContain('drawn by Claude Code')   // 넘김 모드에서 다른 그림은 띠 위
  await ui.post({ height: 99 }, { in: 'band-height' })                              // 상한까지 끌어도(저장 높이 = vis) 넘김 모드가 유지된다
  await settle(clock)
  expect(treeRows(await ui.drawn())).toBe(14)
  await ui.post({ scroll: 1 }, { in: 'band-height' })                               // 띠 안 넘김(휠과 같은 SCROLL 경로)
  await settle(clock)
  expect(await label()).not.toMatch(/스크롤 1~/)                                  // 띠 안 내용이 넘어갔다
  expect((await ui.find({ key: 'band-toggle' })).props.label).toBe('접기 ▾')      // 첫 줄 고정
  expect(await ui.find({ key: 'band-height' })).toBeDefined()                     // 높이 줄 고정
  await ui.unmount()
})

test('테마: 어두운 기본 · light 계열은 밝은 팔레트, 테마가 바뀌면 다시 고른다', async ($, on) => {
  const clock = stubs(on)
  let theme = 'dark'
  on('config.list', () => ({ value: [{ key: 'theme', label: 'Theme', kind: 'choice', value: theme, provider: { plugin: 'engine', tier: 'core' }, isLocked: false }] }) as never)
  on('config.set', (_$, e) => { theme = String(e.value); return { value: e.value } })
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  await settle(clock)
  const badge = async (surface: 'terminal' | 'desktop') => {
    const ui = await $.ui.mount({ ...SITE, surface })
    const t = await ui.find({ type: 'Text', text: ' 작업 ' })
    await ui.unmount()
    return t.props.backgroundColor
  }
  for (const surface of ['terminal', 'desktop'] as const) expect(await badge(surface)).toBe('#FFC4A3')
  await $.config.set({ key: 'theme', value: 'light-daltonized' })
  await settle(clock)
  for (const surface of ['terminal', 'desktop'] as const) expect(await badge(surface)).toBe('#FFD2B8')
})

test('HOME 을 못 읽으면 수집하지 않고 «(조회 실패)» 로 그려진다', async ($, on) => {
  const clock = stubs(on, null) // 기본값 인자는 undefined 를 덮으므로 null 로 «HOME 없음» 을 만든다
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  await settle(clock)
  const ui = await $.ui.mount({ ...SITE, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: 'gpt-6.1-sol/xhigh' })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: /조회 실패/ })).toBeDefined()
  await ui.unmount()
})

test('데이터가 없으면 «(조회 실패)» 로 그려진다', async ($, on) => {
  stubs(on)
  const ui = await $.ui.mount({ ...SITE, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /조회 실패/ })).toBeDefined()
  await ui.unmount()
})
