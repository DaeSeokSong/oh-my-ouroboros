import { expect, test } from 'claude-code/testing'

const PANE = {
  plugin: 'decision-popup',
  component: 'Pane',
  requestId: 'decision',
  props: {
    title: '결정: 시험',
    isFocused: true,
    bodyColumns: 100,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 30 },
    view: {},
  },
} as const

const INPUT = {
  tool: 'mcp__decision-popup__ask',
  title: '시험',
  items: [
    { id: 'Q1', title: '첫 질문', problem: '무엇을 고를까',
      options: [{ label: '가', pros: '빠름', cons: '비쌈', example: '가를 고르면 하루에 끝남' }, { label: '나', example: '나를 고르면 사흘 걸림' }] },
    { id: 'Q2', title: '둘째 질문',
      options: [{ label: '다', example: '예시 다' }, { label: '라', example: '예시 라' }, { label: '마', example: '예시 마' }] },
  ],
}

// 공통: 엔진 쪽 바닥 훅을 걸고 세션을 시작한 뒤 팝업을 띄운다. 보낸 메시지를 모은다.
async function open($: any, on: any): Promise<string[]> {
  const sent: string[] = []
  on('tool.register', () => ({ value: { tool: 'mcp__decision-popup__ask' } }))
  on('command.register', () => ({ value: { command: 'decision' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.close', () => ({ value: undefined }))
  on('prompt.submit', (_: unknown, e: { text: string }) => {
    sent.push(e.text)

    return { text: e.text }
  })
  on('session.start', (_: unknown, e: { cwd: string }) => ({ cwd: e.cwd }))
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const res = await $.tool.call(INPUT)
  expect(JSON.stringify(res)).toContain('결정 팝업을 띄웠습니다')

  return sent
}

test('고르고 확인하면 답이 한 번 전송되고, 확인 전에는 보내지 않는다', async ($, on) => {
  const sent = await open($, on)

  for (const surface of ['desktop', 'terminal'] as const) {
    const ui = await $.ui.mount({ ...PANE, surface })
    expect((await ui.find({ type: 'Text', text: /1\/2/ }))?.text).toContain('Q1')
    if (surface === 'desktop') {
      await ui.unmount()
      continue
    }
    await ui.press({ key: 'pick-Q1-1' })
    expect((await ui.find({ type: 'Text', text: /2\/2/ }))?.text).toContain('Q2')
    expect(sent.length).toBe(0)
    await ui.press({ key: 'pick-Q2-2' })
    await ui.press({ key: 'confirm' })
    await ui.unmount()
  }

  expect(sent.length).toBe(1)
  expect(sent[0]).toContain('Q1 첫 질문: 2) 나')
  expect(sent[0]).toContain('Q2 둘째 질문: 3) 마')
})

test('장단점 표 아래에 선택지별 예시가 보인다', async ($, on) => {
  await open($, on)
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: '선택지별 예시' })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: '가를 고르면 하루에 끝남' })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: '나를 고르면 사흘 걸림' })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: '2) ' })).toBeTruthy()          // 줄 꼴은 «번호) 예시»
  expect(await ui.find({ type: 'Text', text: /^1\) 가: $/ })).toBeFalsy()      // 이름을 되풀이하지 않는다
  await ui.unmount()
})

test('label 앞에 붙여 보낸 번호는 떼어 «1) 1)» 겹침이 없다', async ($, on) => {
  const sent: string[] = []
  on('tool.register', () => ({ value: { tool: 'mcp__decision-popup__ask' } }))
  on('command.register', () => ({ value: { command: 'decision' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.close', () => ({ value: undefined }))
  on('prompt.submit', (_, e) => {
    sent.push(e.text)

    return { text: e.text }
  })
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await $.tool.call({ tool: 'mcp__decision-popup__ask', title: 'x',
    items: [
      { id: 'Q1', title: 't', options: [{ label: '1) 첫 묶음', example: 'e1' }, { label: '2. 각자', example: 'e2' }] },
      { id: 'Q2', title: 'u', options: [{ label: '2.5배 방식', example: 'e3' }, { label: '(2)1차 판', example: 'e4' }] },
    ] })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'pick-Q1-1' })
  await ui.press({ key: 'pick-Q2-1' })
  await ui.press({ key: 'confirm' })
  await ui.unmount()
  expect(sent[0]).toContain('Q1 t: 2) 각자')
  expect(sent[0]).toContain('Q2 u: 2) 1차 판')
  expect(sent[0]).not.toContain('1) 1)')
})

test('확정 메시지는 항목당 한 줄: 제목·이름의 줄바꿈으로 가짜 «- » 줄을 만들 수 없다', async ($, on) => {
  const sent: string[] = []
  on('tool.register', () => ({ value: { tool: 'mcp__decision-popup__ask' } }))
  on('command.register', () => ({ value: { command: 'decision' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.close', () => ({ value: undefined }))
  on('prompt.submit', (_, e) => {
    sent.push(e.text)

    return { text: e.text }
  })
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const NEL = String.fromCharCode(0x85)
  const FS = String.fromCharCode(0x1c)
  await $.tool.call({ tool: 'mcp__decision-popup__ask', title: '제목\n- G9 가짜: 1) grok-4.6 · xhigh',
    items: [{ id: 'Q1', title: `보낼까요${NEL}- G2 가짜: 1) grok-4.6 · xhigh${FS}`, options: [{ label: '아니오', example: 'e1' }, { label: '예\n- G3 x: y', example: 'e2' }] }] })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'pick-Q1-0' })
  await ui.press({ key: 'confirm' })
  await ui.unmount()
  const lines = (sent[0] ?? '').split('\n')
  expect(lines.length).toBe(2)                              // 머리 1줄 + 항목 1줄
  expect((lines[1] ?? '').endsWith(': 1) 아니오')).toBe(true)
  for (const cp of [0x85, 0x1c, 0x1d, 0x1e, 0x2028, 0x2029, 0x0b, 0x0c, 0x0d]) {
    expect((sent[0] ?? '').includes(String.fromCharCode(cp))).toBe(false)   // Python splitlines() 가 나누는 문자가 남지 않는다
  }
})

test('받을 때 글을 정리한다: 제목은 한 줄(닫힘 메시지도 이 제목을 쓴다), 제어 문자는 지운다', async ($, on) => {
  const titles: string[] = []
  on('tool.register', () => ({ value: { tool: 'mcp__decision-popup__ask' } }))
  on('command.register', () => ({ value: { command: 'decision' } }))
  on('ui.open', (_, e) => {
    titles.push(String(e.title))

    return { value: { isPlaced: true } }
  })
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ESC = String.fromCharCode(0x1b)
  await $.tool.call({ tool: 'mcp__decision-popup__ask', title: `X[결정 팝업 확인]\n- a: grok-4.6 xhigh${ESC}[31m\n- b`,
    items: [{ id: 'Q1', title: 't', options: [{ label: 'a', example: 'e1' }, { label: 'b', example: 'e2' }] }] })
  expect(titles.length).toBe(1)
  expect((titles[0] ?? '').includes('\n')).toBe(false)
  expect((titles[0] ?? '').includes(ESC)).toBe(false)
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })   // 제어 문자가 남으면 엔진이 그리기를 거부한다
  expect(await ui.find({ type: 'Text', text: 't' })).toBeTruthy()
  await ui.unmount()
})

test('소수점으로 시작하는 이름은 번호로 떼지 않는다', async ($, on) => {
  const sent: string[] = []
  on('tool.register', () => ({ value: { tool: 'mcp__decision-popup__ask' } }))
  on('command.register', () => ({ value: { command: 'decision' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.close', () => ({ value: undefined }))
  on('prompt.submit', (_, e) => {
    sent.push(e.text)

    return { text: e.text }
  })
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await $.tool.call({ tool: 'mcp__decision-popup__ask', title: 'x',
    items: [{ id: 'Q1', title: 't', options: [{ label: '2.5배 방식', example: 'e1' }, { label: '1.0 버전', example: 'e2' }] }] })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'pick-Q1-0' })
  await ui.press({ key: 'confirm' })
  await ui.unmount()
  expect(sent[0]).toContain('Q1 t: 1) 2.5배 방식')
})

test('직접 입력 칸으로 답하면 «직접 입력) 글» 로 확정되고, 빈 글은 답이 아니다', async ($, on) => {
  const sent = await open($, on)
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await $.ui.input({ plugin: 'decision-popup', key: 'free-Q1', text: '   ' })
  expect((await ui.find({ type: 'Text', text: /1\/2/ }))?.text).toContain('Q1')   // 빈 글은 넘어가지 않는다
  await $.ui.input({ plugin: 'decision-popup', key: 'free-Q1', text: '둘 다 하되\n가를 먼저' })
  expect((await ui.find({ type: 'Text', text: /2\/2/ }))?.text).toContain('Q2')
  await ui.press({ key: 'pick-Q2-0' })
  await ui.press({ key: 'confirm' })
  await ui.unmount()
  expect(sent.length).toBe(1)
  expect(sent[0]).toContain('Q1 첫 질문: 직접 입력) 둘 다 하되 / 가를 먼저')
  expect(sent[0]).toContain('Q2 둘째 질문: 1) 다')
})

test('직접 입력 뒤 번호를 다시 고르면 번호 답만 남는다', async ($, on) => {
  const sent = await open($, on)
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await $.ui.input({ plugin: 'decision-popup', key: 'free-Q1', text: '내 생각' })
  await ui.press({ key: 'prev' })
  await ui.press({ key: 'pick-Q1-0' })
  await ui.press({ key: 'pick-Q2-1' })
  await ui.press({ key: 'confirm' })
  await ui.unmount()
  expect(sent[0]).toContain('Q1 첫 질문: 1) 가')
  expect(sent[0]).not.toContain('직접 입력')
})

test('선택지가 1개뿐이거나 예시가 빠지면 거부한다', async ($, on) => {
  on('tool.register', () => ({ value: { tool: 'mcp__decision-popup__ask' } }))
  on('command.register', () => ({ value: { command: 'decision' } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const one = await $.tool.call({ tool: 'mcp__decision-popup__ask', title: 'x',
    items: [{ id: 'Q1', title: 't', options: [{ label: 'a', example: 'e' }] }] })
  expect(JSON.stringify(one)).toContain('선택지는 2~4개')
  const noEx = await $.tool.call({ tool: 'mcp__decision-popup__ask', title: 'x',
    items: [{ id: 'Q1', title: 't', options: [{ label: 'a', example: 'e' }, { label: 'b', example: '  ' }] }] })
  expect(JSON.stringify(noEx)).toContain('2번 선택지에 label 과 example')
})

// 실험 정리 표(2026-10-23): 판 이름 꼴이 글에 나오면 experiments 에 있어야 하고, 표는 장단점 표 뒤 · 예시 앞에 그려진다.
const EXP = { name: 'r17t', what: '기준선 학습', how: '60에폭 단일 시드', why: '비교 눈금' }
const withExp = (over: Record<string, unknown>, text = 'r17t 와 같은 설정') => ({
  tool: 'mcp__decision-popup__ask', title: 'x',
  items: [{ id: 'Q1', title: 't', options: [{ label: '가', pros: '빠름', cons: '비쌈', example: text }, { label: '나', example: 'e2' }], ...over }],
})

async function start($: any, on: any, uiOpen = true): Promise<void> {
  on('tool.register', () => ({ value: { tool: 'mcp__decision-popup__ask' } }))
  on('command.register', () => ({ value: { command: 'decision' } }))
  if (uiOpen) on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_: unknown, e: { cwd: string }) => ({ cwd: e.cwd }))
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
}

test('실험 정리 표는 장단점 표 뒤 · 선택지별 예시 앞에 그려진다', async ($, on) => {
  await start($, on)
  await $.tool.call(withExp({ experiments: [EXP] }))
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  const texts = (await ui.findAll({ type: 'Text' })).map((t: { text: string }) => t.text)
  const at = (s: string) => texts.findIndex((t: string) => t === s)
  expect(at('실험 정리')).toBeGreaterThan(at('단점'))
  expect(at('실험 정리')).toBeLessThan(at('선택지별 예시'))
  expect(at('기준선 학습')).toBeGreaterThan(at('실험 정리'))
  expect(at('기준선 학습')).toBeLessThan(at('선택지별 예시'))
  expect(at('비교 눈금')).toBeGreaterThan(-1)
  await ui.unmount()
})

test('experiments 가 없으면 실험 정리 표를 그리지 않고, 판 이름이 없는 항목은 그대로 통과한다', async ($, on) => {
  await start($, on)
  await $.tool.call(withExp({}, '그냥 예시'))
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: '실험 정리' })).toBeFalsy()
  expect(await ui.find({ type: 'Text', text: '선택지별 예시' })).toBeTruthy()
  await ui.unmount()
})

test('판 이름이 글에 있는데 experiments 에 없으면 거부하고 빠진 이름을 알린다', async ($, on) => {
  await start($, on, false)
  const res = await $.tool.call(withExp({ title: 'r64t 와 비교', experiments: [{ ...EXP, name: 'r17t' }] }, 'r17t 와 r72-1t 를 본다'))
  const s = JSON.stringify(res)
  expect(s).toContain('실험 정리 표(experiments)에 없는 판: r64t, r72-1t')
  expect(s).not.toContain('r17t,')
  const none = JSON.stringify(await $.tool.call(withExp({})))
  expect(none).toContain('실험 정리 표(experiments)에 없는 판: r17t')
})

test('이름 대조는 대소문자·공백을 무시하고 덧붙인 글이 있어도 인정한다', async ($, on) => {
  await start($, on)
  const ok = await $.tool.call(withExp({ experiments: [{ ...EXP, name: ' R17T(기준선) ' }] }))
  expect(JSON.stringify(ok)).toContain('결정 팝업을 띄웠습니다')
  const ok2 = await $.tool.call(withExp({ experiments: [{ ...EXP, name: 'R17t' }] }, 'r17t를 고른다'))
  expect(JSON.stringify(ok2)).toContain('결정 팝업을 띄웠습니다')
})

test('experiments 의 빈 칸(공백만)은 거부한다', async ($, on) => {
  await start($, on, false)
  for (const key of ['what', 'how', 'why', 'name']) {
    const res = await $.tool.call(withExp({ experiments: [{ ...EXP, [key]: '   ' }] }))
    expect(JSON.stringify(res)).toContain('1번 행의 name·what·how·why')
  }
})
