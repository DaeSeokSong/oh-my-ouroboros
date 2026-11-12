import { expect, test } from 'claude-code/testing'
import { cellWidth, clip, lineWidth, splitAt } from '../hooks/band/width.js'
import { BIG_HEIGHT, BTN_RESERVE, DETAIL_BTN_RESERVE, MIN_RESERVE, buildBand, effectiveSplit, sanitize, shortName, windowBand } from '../hooks/band/model.js'
import { needsCollect, validCache, wantsBand } from '../hooks/band/poll.js'
import { themeKind } from '../hooks/band/theme.js'
import { PALETTES, toTree, treeRows, treeTexts } from '../hooks/band/view.js'
import { ackText, ackedSet, noticeText, parsePending, plan } from '../hooks/band/propagate.js'

// 개정 27: 접힌 띠 첫 줄 오른쪽에 마스킹 버튼(옛 «가림 켬», 지금 «🔒 마스킹 on»)이 늘어 작업 줄이 쓰는 폭이 BTN_RESERVE - 7(옛 예약) 칸 줄었다. 사다리 시험은 그만큼 열 수를 옮겨 같은 작업 줄 폭에서 본다.
const EXTRA = BTN_RESERVE - 7
// 2026-11-03: 버튼 칩(여백 포함)과 모바일 버튼으로 접힌 띠 오른쪽 예약이 29 → BTN_RESERVE 로 늘었다. SHIFT 는 옛 80열과 같은 작업 줄 폭을 얻는 열 수 보정,
// NARROW 는 가장 좁은 단계(상세 버튼만)에서 옛 «columns - 4 - 7» 과 같은 작업 줄 폭을 얻는 열 수 보정이다.
const SHIFT = BTN_RESERVE - 29
const NARROW = MIN_RESERVE - 7

// ---- 하네스 변경 전파의 받는 쪽(intent/2026-10-21-harness-change-propagation-gate.md 개정 1) ----
const SELF_SID = '11111111-1111-4111-8111-111111111111'
const PEER_SID = '22222222-2222-4222-8222-222222222222'
const PENDING = [
  JSON.stringify({ ts: 100, hash: 'aaaaaaa01', subject: '옛 커밋', author: PEER_SID }),
  JSON.stringify({ ts: 200, hash: 'bbbbbbb02', subject: '내 커밋', author: SELF_SID }),
  JSON.stringify({ ts: 300, hash: 'ccccccc03', subject: 'feat: 새 규칙‮', author: PEER_SID }),
  'not json',
  JSON.stringify({ ts: 400, hash: 'XYZ', subject: '깨진 해시' }),
].join('\n')

test('전파 받는 쪽: 대기 줄 정화 · 자기 커밋/시작 전 커밋/새 커밋 가르기', async () => {
  const rows = parsePending(PENDING)
  expect(rows.map(r => r.hash)).toEqual(['aaaaaaa01', 'bbbbbbb02', 'ccccccc03'])   // 깨진 줄·해시는 버린다
  expect(rows[2].subject).toBe('feat: 새 규칙')                                    // 양방향 제어 글자는 지운다
  const p = plan(rows, ackedSet(''), SELF_SID, 150)
  expect(p.baseline.map(r => r.hash)).toEqual(['aaaaaaa01'])                       // 세션이 뜨기 전 커밋은 알리지 않는다
  expect(p.self.map(r => r.hash)).toEqual(['bbbbbbb02'])                           // 자기 커밋도 알리지 않는다
  expect(p.deliver.map(r => r.hash)).toEqual(['ccccccc03'])
  const ack = ackText('', [['mod', p.deliver], ['self', p.self], ['baseline', p.baseline]], 500)
  expect(ack).toBe('ccccccc03\t500\tmod\nbbbbbbb02\t500\tself\naaaaaaa01\t500\tbaseline\n')
  const again = plan(rows, ackedSet(ack), SELF_SID, 150)                           // 받은 뒤에는 다시 넣지 않는다
  expect(again.deliver.length + again.self.length + again.baseline.length).toBe(0)
  expect(noticeText(p.deliver)).toContain('[하네스 변경 알림 · 회신 불요]')
  expect(noticeText(p.deliver)).toContain('ccccccc03 feat: 새 규칙')
  expect(noticeText(p.deliver)).toContain('회신하거나 사용자에게 따로 보고하지 마십시오')
})

test('전파 받는 쪽: 보이지 않는 글자(폭 없는 문자 · BOM · 태그 문자)도 지운다', async () => {
  const hidden = 'a​b‏c⁠d﻿e' + String.fromCodePoint(0xe0041, 0xe007f) + 'f'
  const rows = parsePending(JSON.stringify({ ts: 1, hash: 'ddddddd04', subject: hidden, author: '' }))
  expect(rows[0].subject).toBe('abcdef')
})

test('전파 받는 쪽: 받음 기록은 마지막 500줄만', async () => {
  const many = Array.from({ length: 600 }, (_, i) => ({ hash: (i + 1).toString(16).padStart(9, '0'), ts: i, subject: '', author: '' }))
  const text = ackText('', [['mod', many]], 1)
  const lines = text.trim().split('\n')
  expect(lines.length).toBe(500)
  expect(lines[499].startsWith((600).toString(16).padStart(9, '0'))).toBe(true)
})

test('cellWidth counts Hangul as 2', async () => {
  expect(cellWidth('작업 abc')).toBe(8)
  expect(cellWidth('GPU 대기4')).toBe(9)
  expect(cellWidth('●○·▸▾')).toBe(5)
})

const server = {
  gpus: [0, 1, 2, 5].map(i => ({ i, util: 0, used: 14, total: 46080 }))
    .concat([{ i: 3, util: 96, used: 26419, total: 81920 }, { i: 4, util: 100, used: 26417, total: 81920 }]),
  mem: { total: 503 * 2 ** 30, avail: 212 * 2 ** 30 },
  disk: { total: 931 * 2 ** 30, avail: 121 * 2 ** 30 },
  sessions: [
    { sid: 'self', name: '[Harness] Manager', status: 'busy' },
    { sid: 'b', name: '[PRJ] Manager', status: 'busy' },
    { sid: 'c', name: '[PRJ] 2.0.0', status: 'idle' },
    { sid: 'd', name: '[Research] Benchmark Labs', status: 'busy' }],
}
const idle = { codex: [], grok: [], train: { running: [], ended: [] } }
const noSess = { ...server, sessions: [] } // 학습 칸 글자만 보는 시험은 세션 칸이 줄 끝에 붙지 않게 세션을 비운다
// 버튼 세그먼트(button: true)는 글자 비교에서 뺀다. 버튼은 view 가 오른쪽 끝에 따로 붙인다.
const txt = row => row.filter(s => !s.button).map(s => s.text).join('')
// 펼친 보기 한 줄을 왼쪽 반(작업)과 오른쪽 반(서버)의 글자로 가른다(개정 13). 반 폭 colW = (columns - 4 - 3) ÷ 2, 가운데 ` │ ` 는 왼쪽이 colW 칸을 채운 바로 뒤에 온다.
const halves = (row, columns: number) => {
  const colW = Math.floor((columns - 7) / 2), cells = row.filter(s => !s.button)
  let w = 0, i = 0
  while (i < cells.length && w < colW) w += cellWidth(cells[i++].text)
  return [cells.slice(0, i).map(s => s.text).join('').trimEnd(), cells.slice(i + 1).map(s => s.text).join('')]
}
const LEFT = (rows, columns: number) => rows.map(r => halves(r, columns)[0])
const RIGHT = (rows, columns: number) => rows.map(r => halves(r, columns)[1])

test('평소 80열: 시안 카드 1과 같은 글자', async () => {
  const rows = buildBand({ work: idle, server, selfSid: 'self', columns: 80, expanded: false })
  expect(rows.length).toBe(2)
  expect(txt(buildBand({ work: idle, server, selfSid: 'self', columns: 80 + SHIFT, expanded: false })[0])).toBe(' 작업  이상 없음 │ 세션 ●2 ○1') // 세션 칸은 작업 줄 끝(개정 11). 버튼 칩(2026-11-03)이 늘어 옛 80열과 같은 작업 줄 폭은 80 + SHIFT 열
  expect(txt(rows[0])).toBe(' 작업  이상 없음')   // 80열 그대로는 작업 줄이 26칸이라 세션 칸이 사다리에서 먼저 빠진다
  expect(txt(rows[1])).toBe(' 서버  GPU 대기4  3 96% 26G  4 100% 26G │ 여유 메모리 212G · 디스크 121G') // 서버 줄에는 세션이 없고, 남는 폭에 GPU 메모리 «26G» 가 다시 보인다
  for (const r of rows) expect(lineWidth(r)).toBeLessThanOrEqual(76) // 띠 Box 의 좌우 여백 1칸씩 → columns - 4
  expect(rows[0][0]).toEqual({ text: ' 작업 ', tone: 'workBadge' })
  expect(rows[1][0]).toEqual({ text: ' 서버 ', tone: 'srvBadge' })
  expect(rows[1].filter(s => s.text === ' │ ').every(s => s.tone === 'sep')).toBe(true)
})

test('접힌 띠의 세션 칸은 작업 줄에 있고 넓은 열에서도 개수만(이름은 펼친 보기에서만)', async () => {
  for (const columns of [120, 200, 300]) {
    const rows = buildBand({ work: idle, server, selfSid: 'self', columns, expanded: false })
    expect(txt(rows[0])).toContain('세션 ●2 ○1')
    expect(txt(rows[0])).not.toContain('Manager')
    expect(txt(rows[1])).not.toContain('세션')
  }
})

test('디스크 여유 14% 는 노랑', async () => {
  const rows = buildBand({ work: idle, server, selfSid: 'self', columns: 80, expanded: false })
  const disk = rows[1].find(s => s.text === '121G')
  expect(disk.tone).toBe('warn')
})

test('조회 실패 칸', async () => {
  const rows = buildBand({ work: { codex: [], grok: [], train: null }, server: { ...server, gpus: null, mem: null, disk: null },
    selfSid: 'self', columns: 80, expanded: false })
  expect(txt(rows[0])).toContain('학습 (조회 실패)')
  expect(txt(rows[1])).toContain('GPU (조회 실패)')
  expect(txt(rows[1])).toContain('여유 (조회 실패)')
})

test('외부 모델 호출: 접힌 띠는 작업N 만, 펼친 보기는 모델·effort 그대로(개정 13)', async () => {
  const work = { codex: [{ model: 'gpt-6.1-sol', effort: 'xhigh' }], grok: [{ model: 'grok-4.7', effort: 'high' }],
    train: { running: ['a', 'b'], ended: ['c'] } }
  const rows = buildBand({ work, server, selfSid: 'self', columns: 120, expanded: false })
  expect(txt(rows[0])).toBe(' 작업  작업2 │ 학습 2판 실행 · 1판 종료 │ 세션 ●2 ○1')   // 세션 칸은 작업 줄 끝(학습 칸 뒤)
  expect(rows[0].find(s => s.text === '작업2').tone).toBe('runBold')
  expect(txt(buildBand({ work: { ...idle, codex: [{ model: 'gpt-6.1-sol', effort: 'xhigh' }] }, server: noSess, selfSid: 'self', columns: 80, expanded: false })[0])).toBe(' 작업  작업1')
  const open = buildBand({ work, server, selfSid: 'self', columns: 120, expanded: true })
  expect(LEFT(open, 120)[1]).toBe('Codex gpt-6.1-sol/xhigh  Grok grok-4.7/high')   // 개정 26: 내용은 둘째 줄부터
})

test('상세 보기는 GPU 6장을 모두 보인다', async () => {
  const rows = buildBand({ work: idle, server, selfSid: 'self', columns: 80, expanded: true })
  const all = rows.map(txt).join('\n')
  for (const g of ['0 0% 0/45G', '3 96% 26/80G', '5 0% 0/45G']) expect(all).toContain(g)
  expect(all).toContain('[Harness]')   // 80열 왼쪽 반은 좁아 세션 표의 이름 열이 줄어든다(개정 21, 넘치면 …)
  for (const r of rows) expect(lineWidth(r)).toBeLessThanOrEqual(76)
})

// ---- 검수 반영(2026-10-15) ----
const GB = 2 ** 30
const ch = (...codes: number[]) => String.fromCharCode(...codes) // 소스에 제어·양방향 제어 글자를 직접 넣지 않는다
const BAD = ch(0x1b, 0x07, 0x85, 0x202e, 0x2066, 0x2028, 0x2029, 0x202a, 0x2069)
const hasBad = (s: string) => [...s].some(c => {
  const n = c.codePointAt(0)!
  return n < 0x20 || (n >= 0x7f && n <= 0x9f) || n === 0x2028 || n === 0x2029 || (n >= 0x202a && n <= 0x202e) || (n >= 0x2066 && n <= 0x2069)
})
const allText = rows => rows.map(r => r.map(s => s.text).join('')).join('\n')

test('정화: 이름의 제어·양방향 제어 문자는 출력에 없다', async () => {
  const sv = { ...server, sessions: [{ sid: 'self', name: ch(0x1b) + ']52;c;x' + ch(0x07) + BAD, status: 'busy' }] }
  const out = buildBand({ work: idle, server: sv, selfSid: 'x', columns: 120, expanded: true })
  expect(out.some(r => hasBad(r.map(s => s.text).join('')))).toBe(false)
  expect(allText(out)).toContain(']52;c;x')
})

test('정화: 상속 키 status(constructor 등)는 예외 없이 ◐', async () => {
  for (const status of ['constructor', '__proto__', 'toString', 'hasOwnProperty']) {
    const sv = { ...server, sessions: [{ sid: 'b', name: 'n', status }] }
    const out = buildBand({ work: idle, server: sv, selfSid: 'self', columns: 120, expanded: true })
    expect(allText(out)).toContain('◐ n')
  }
})

test('정화: 숫자가 유한하지 않거나 total ≤ 0 이면 그 칸만 조회 실패', async () => {
  const row = sv => txt(buildBand({ work: idle, server: sv, selfSid: 'self', columns: 160, expanded: false })[1])
  const a = row({ ...server, gpus: [{ i: 0, util: NaN, used: 1, total: 2 }], mem: { total: 0, avail: 5 } })
  expect(a).toContain('GPU (조회 실패)')
  expect(a).toContain('메모리 (조회 실패)')
  expect(a).toContain('디스크 121')
  const b = row({ ...server, disk: { total: Infinity, avail: 1 } })
  expect(b).toContain('디스크 (조회 실패)')
  expect(b).toContain('메모리 212')
  const c = row({ ...server, mem: { total: '10', avail: 5 }, disk: { total: 10, avail: null } })
  expect(c).toContain('여유 (조회 실패)')
})

test('정화: 문자열은 셀 폭 40칸으로 자른다, 이상한 모양 입력도 예외 없음', async () => {
  const long = { ...server, sessions: [{ sid: 'b', name: '가'.repeat(60), status: 'busy' }] }
  expect(cellWidth(sanitize(long, idle).server.sessions[0].name)).toBe(40)
  const out = buildBand({ work: idle, server: long, selfSid: 'self', columns: 200, expanded: true })
  const seg = out.flat().find(s => !s.button && s.text.startsWith('가'))   // 마스킹 버튼(개정 27)은 글자가 «가» 로 시작하지 않아도 버튼은 뺀다
  expect(cellWidth(seg.text)).toBe(20)   // 세션 표의 이름 열은 20칸까지(개정 21, 넘치면 …)
  expect(seg.text.trimEnd().endsWith('…')).toBe(true)
  const s = sanitize(null, 'x')
  expect(s.server.gpus).toBe(null)
  expect(s.work.codex).toBe(null)
  buildBand({ work: 5, server: [], selfSid: 'self', columns: 80, expanded: false })
})

const hotDisk = { ...server, disk: { total: 931 * GB, avail: 40 * GB } }

test('빨강 디스크는 줄여도 숨기지 않는다', async () => {
  for (const columns of [52, 56, 60]) {
    const row = buildBand({ work: idle, server: hotDisk, selfSid: 'self', columns, expanded: false })[1]
    const d = row.find(s => s.text === '40G')
    expect(d !== undefined && d.tone === 'hot').toBe(true)
    expect(lineWidth(row)).toBeLessThanOrEqual(columns - 4)
  }
})

// GPU 가 많이 사용 중이면 GPU 칸이 길어 줄 끝 자르기가 빨강 디스크를 잘라냈다(재검수). 12단계가 GPU 칸을 접는다.
const busyGpus = (n: number, used = 20000) => Array.from({ length: n }, (_, i) => ({ i, util: 50, used, total: 46080 }))

test('빨강 디스크: GPU 8장 사용 중 80열·6장 사용 중 60열에서도 서버 줄에 남는다', async () => {
  for (const [n, columns] of [[8, 80], [6, 60]]) {
    const sv = { ...hotDisk, gpus: busyGpus(n) }
    const row = buildBand({ work: idle, server: sv, selfSid: 'self', columns, expanded: false })[1]
    const d = row.find(s => s.text === '40G')
    expect(d !== undefined && d.tone === 'hot').toBe(true)
    expect(lineWidth(row)).toBeLessThanOrEqual(columns - 4)
    expect(txt(row)).toContain(`GPU 사용${n}`)
  }
})

test('12단계 GPU 접기: 사용 GPU 중 hot 이 있으면 사용N 빨강·warn 이면 노랑·대기는 M 만큼', async () => {
  const at = (gpus, columns = 44) => buildBand({ work: idle, server: { ...hotDisk, gpus }, selfSid: 'self', columns, expanded: false })[1]
  const hot = at([...busyGpus(2), { i: 2, util: 50, used: 44000, total: 46080 }, { i: 3, util: 0, used: 14, total: 46080 }])
  expect(hot.find(s => s.text === '사용3').tone).toBe('hot')
  expect(txt(hot)).toContain('GPU 사용3 대기1')
  const warn = at([...busyGpus(2), { i: 2, util: 50, used: 36000, total: 46080 }])
  expect(warn.find(s => s.text === '사용3').tone).toBe('warn')
  expect(txt(warn)).toContain('GPU 사용3 │')   // 대기 0 이면 대기 칸 없음
  expect(at(busyGpus(2)).find(s => s.text === '사용2').tone).toBe('base')
})

test('13단계: 매우 좁아도 빨강 디스크가 GPU 칸 앞으로 와서 잘리지 않는다', async () => {
  const row = buildBand({ work: idle, server: { ...hotDisk, gpus: busyGpus(8) }, selfSid: 'self', columns: 28, expanded: false })[1]
  const d = row.find(s => s.text === '40G')
  expect(d !== undefined && d.tone === 'hot').toBe(true)
  expect(lineWidth(row)).toBeLessThanOrEqual(24)
})

test('정상 디스크는 좁으면 숨는다', async () => {
  const row = buildBand({ work: idle, server, selfSid: 'self', columns: 52, expanded: false })[1]
  expect(txt(row)).toBe(' 서버  GPU 대기4  3 96%  4 100% │ 여유 212G')
})

test('clip: 넘치면 셀 폭으로 자르고 … 를 붙인다', async () => {
  const row = [{ text: '작업 ', tone: 'tag' }, { text: '가나다라마바사', tone: 'base' }]
  expect(clip(row, 20)).toBe(row)
  const c = clip(row, 9)
  expect(lineWidth(c)).toBeLessThanOrEqual(9)
  expect(c[c.length - 1].text.endsWith('…')).toBe(true)
  expect(txt(clip([{ text: 'abcde', tone: 'base' }, { text: 'f', tone: 'base' }], 5))).toBe('abcd…')
  expect(clip(row, 0).length).toBe(0)
})

test('45열에서 Codex·Grok·학습이 함께여도 모든 줄이 한도 안', async () => {
  const work = { codex: [{ model: 'gpt-6.1-sol', effort: 'xhigh' }], grok: [{ model: 'grok-4.7', effort: 'high' }],
    train: { running: ['a', 'b'], ended: ['c'] } }
  for (const expanded of [false, true]) {
    const rows = buildBand({ work, server, selfSid: 'self', columns: 45, expanded })
    for (const r of rows) expect(lineWidth(r)).toBeLessThanOrEqual(41)
    expect(lineWidth(rows[0].filter(s => !s.button))).toBeLessThanOrEqual(41 - 7)
  }
})

test('상세 보기: 긴 세션 이름·작업 모델이어도 60열·120열에서 모든 줄이 한도 안', async () => {
  const names = ['가'.repeat(40), 'x'.repeat(200), '[PRJ] ' + '나'.repeat(30)]
  const sv = { ...server, sessions: names.map((name, i) => ({ sid: 's' + i, name, status: 'busy' })) }
  const work = { codex: [{ model: 'm'.repeat(80), effort: 'xhigh' }, { model: 'gpt-6.1-sol', effort: 'high' }], grok: [],
    train: { running: ['a'], ended: [] } }
  for (const columns of [60, 120]) {
    const rows = buildBand({ work, server: sv, selfSid: 'self', columns, expanded: true })
    for (const r of rows) expect(lineWidth(r)).toBeLessThanOrEqual(columns - 4)
    expect(lineWidth(rows[0].filter(s => !s.button))).toBeLessThanOrEqual(columns - 4 - 7)
  }
})

test('GPU 메모리 90% 이상 빨강 · 75% 이상 노랑 · 그 아래 기본', async () => {
  const tone = (used: number) => {
    const sv = { ...server, gpus: [{ i: 0, util: 50, used: used * 1024, total: 100 * 1024 }] }
    const row = buildBand({ work: idle, server: sv, selfSid: 'self', columns: 120, expanded: false })[1]
    return row.find(s => s.text === `${used}/100G` || s.text === `${used}G`).tone
  }
  expect(tone(90)).toBe('hot')
  expect(tone(89)).toBe('warn')
  expect(tone(75)).toBe('warn')
  expect(tone(74)).toBe('base')
})

test('작업 줄 사다리: 작업N 은 폭이 줄어도 그대로, 학습 칸만 줄어든다', async () => {
  const work = { codex: [{ model: 'gpt-6.1-sol', effort: 'xhigh' }], grok: [{ model: 'grok-4.7', effort: 'high' }],
    train: { running: ['a', 'b'], ended: ['c'] } }
  const at = (columns: number) => txt(buildBand({ work, server: noSess, selfSid: 'self', columns: columns + EXTRA, expanded: false })[0])
  expect(at(74)).toBe(' 작업  작업2 │ 학습 2판 실행 · 1판 종료')
  expect(at(44)).toBe(' 작업  작업2 │ 학습 실행2 종료1')
  expect(at(36)).toBe(' 작업  작업2 │ 학습 실행2')
})

// ---- GPU 별 학습 판(개정 8, 2026-10-15) ----
const RUN_A = { gpu: 3, name: 'exp-demo-1a-x72-1t', max_epochs: 60, metric: 'val_score', last: true,
  ckpts: [{ epoch: 5, value: -0.3136 }, { epoch: 10, value: -0.2688 }, { epoch: 15, value: -0.2571 }] }
const RUN_B = { gpu: 4, name: 'exp-demo-1b-x72t', max_epochs: 60, metric: '', ckpts: [], last: false }
const withTrain = { ...noSess, train: [RUN_A, RUN_B] }

test('shortName: 영문자+숫자 조각부터 끝까지, 없으면 전체', async () => {
  expect(shortName('exp-demo-1a-x72-1t')).toBe('x72-1t')
  expect(shortName('exp-demo-1b-x72t')).toBe('x72t')
  expect(shortName('plain-name')).toBe('plain-name')
  expect(shortName('?')).toBe('?')
})

test('학습 판: 80열 접힌 띠는 76칸 이내이고 판 이름·에폭 없이 GPU 별 판 수만 보인다(개정 15)', async () => {
  const rows = buildBand({ work: idle, server: withTrain, selfSid: 'self', columns: 80 + SHIFT, expanded: false })
  expect(txt(rows[0])).toBe(' 작업  학습 GPU3 1  GPU4 1')
  for (const r of rows) expect(lineWidth(r)).toBeLessThanOrEqual(76 + SHIFT)
  expect(txt(rows[0])).not.toContain('a72')
  expect(txt(rows[0])).not.toContain('/60')
  const ended = { codex: [], grok: [], train: { running: [], ended: ['c'] } }
  expect(txt(buildBand({ work: ended, server: withTrain, selfSid: 'self', columns: 80 + SHIFT, expanded: false })[0]))
    .toBe(' 작업  학습 GPU3 1  GPU4 1 · 1판 종료')
})

test('학습 판: 폭을 줄이면 종료 표기가 먼저 줄고 마지막에 실행N', async () => {
  const at = (columns: number) => txt(buildBand({ work: idle, server: withTrain, selfSid: 'self', columns: columns + EXTRA, expanded: false })[0])
  expect(at(58)).toBe(' 작업  학습 GPU3 1  GPU4 1')
  expect(at(40)).toBe(' 작업  학습 GPU3 1  GPU4 1')
  expect(at(34)).toBe(' 작업  학습 실행2')   // 5단계: GPU 묶음 → 실행N
  expect(at(30)).toBe(' 작업  학습 실행2')
  const ended = { codex: [], grok: [], train: { running: [], ended: ['c'] } }
  expect(txt(buildBand({ work: ended, server: withTrain, selfSid: 'self', columns: 44 + EXTRA, expanded: false })[0]))
    .toBe(' 작업  학습 GPU3 1  GPU4 1 종료1')
  for (const columns of [30, 34, 42, 52, 58, 80]) {
    const r = buildBand({ work: idle, server: withTrain, selfSid: 'self', columns, expanded: false })[0]
    expect(lineWidth(r.filter(s => !s.button))).toBeLessThanOrEqual(columns - 4 - 7)
  }
})

// 끝낸 에폭(1부터 센 개수) done: 펼친 보기의 판 줄에만 «17/60» (접미 없음, 모름은 ?/60). 접힌 띠에는 에폭이 없다(개정 15).
const withDone = { ...noSess, train: [{ ...RUN_A, done: 17 }, { ...RUN_B, done: 9 }] }

test('학습 판 done: 접힌 띠에는 끝낸 에폭이 없고 판 수만, 폭을 줄이면 실행N', async () => {
  const at = (columns: number, sv = withDone) => txt(buildBand({ work: idle, server: sv, selfSid: 'self', columns: columns + EXTRA, expanded: false })[0])
  for (const columns of [80, 58, 50, 42]) {
    expect(at(columns)).toBe(' 작업  학습 GPU3 1  GPU4 1')
    expect(at(columns)).not.toMatch(/17|\/60/)
  }
  expect(at(30)).toBe(' 작업  학습 실행2')
  for (const columns of [30, 34, 42, 50, 58, 80]) {
    const r = buildBand({ work: idle, server: withDone, selfSid: 'self', columns, expanded: false })[0]
    expect(lineWidth(r.filter(s => !s.button))).toBeLessThanOrEqual(columns - 4 - 7)
  }
})

test('학습 판 done: done·max_epochs 를 몰라도 접힌 띠는 GPU 별 판 수 그대로', async () => {
  const at = (train, columns = 80) => txt(buildBand({ work: idle, server: { ...noSess, train }, selfSid: 'self', columns, expanded: false })[0])
  expect(at([{ ...RUN_A, done: null }])).toBe(' 작업  학습 GPU3 1')
  expect(at([{ ...RUN_A, done: null }], 30 + NARROW)).toBe(' 작업  학습 GPU3 1')
  expect(at([{ ...RUN_B, max_epochs: null, done: 9 }])).toBe(' 작업  학습 GPU4 1')
  expect(at([{ ...RUN_A, done: 17 }, RUN_B])).toBe(' 작업  학습 GPU3 1  GPU4 1')
  expect(at([{ ...RUN_B, max_epochs: null, done: null }])).toBe(' 작업  학습 GPU4 1')
})

test('학습 판 done: 펼친 보기는 짧은 이름 + 17/60(접미 없음), 모르면 ?/60, 판마다 한 줄이고 지표·체크포인트는 없다', async () => {
  const lines = LEFT(buildBand({ work: idle, server: withDone, selfSid: 'self', columns: 240, expanded: true }), 240)   // 반 폭 116: 줄이 잘리지 않는다
  expect(lines[0]).toBe(' 작업')   // 개정 26: 첫 줄은 배지뿐이고 내용은 둘째 줄부터, 들여쓰기 없음
  expect(lines[1]).toBe('학습 GPU3 x72-1t  17/60  last')
  expect(lines[2]).toBe('     GPU4 x72t  9/60  last 없음')   // «학습 » 폭 5칸
  expect(lines.join('\n')).not.toMatch(/지표|체크포인트|val_score|e15/)
  const nodone = LEFT(buildBand({ work: idle, server: withTrain, selfSid: 'self', columns: 240, expanded: true }), 240)
  expect(nodone[1]).toContain('x72-1t  ?/60  last')
  expect(nodone[1]).not.toContain('17/60')
  const only = LEFT(buildBand({ work: idle, server: { ...noSess, train: [{ ...RUN_B, max_epochs: null, done: 9 }] }, selfSid: 'self', columns: 240, expanded: true }), 240)
  expect(only[1]).toBe('학습 GPU4 x72t  9  last 없음')
  const none = LEFT(buildBand({ work: idle, server: { ...noSess, train: [{ ...RUN_B, max_epochs: null, done: null }] }, selfSid: 'self', columns: 240, expanded: true }), 240)
  expect(none[1]).toBe('학습 GPU4 x72t  last 없음')
})

test('학습 정화 done: 0 이상 정수만, 아니면 null', async () => {
  const done = d => sanitize({ ...server, train: [{ ...RUN_B, done: d }] }, idle).server.train[0].done
  expect(done(17)).toBe(17)
  expect(done(0)).toBe(0)
  for (const bad of ['17', -1, 1.5, NaN, Infinity, null, undefined]) expect(done(bad)).toBe(null)
})

test('학습 판: gpu 를 모르는 판은 판마다 GPU? 1', async () => {
  const sv = { ...noSess, train: [{ ...RUN_B, max_epochs: null, gpu: null }] }
  expect(txt(buildBand({ work: idle, server: sv, selfSid: 'self', columns: 80, expanded: false })[0])).toBe(' 작업  학습 GPU? 1')
  const two = { ...noSess, train: [{ ...RUN_A, gpu: null }, { ...RUN_B, gpu: null }] }
  expect(txt(buildBand({ work: idle, server: two, selfSid: 'self', columns: 80, expanded: false })[0])).toBe(' 작업  학습 GPU? 1  GPU? 1')
})

test('학습 판: server.train 이 null 이면 work.train 으로 대신하고 빈 목록이면 서버 쪽을 따른다', async () => {
  const work = { codex: [], grok: [], train: { running: ['a', 'b'], ended: [] } }
  const nul = buildBand({ work, server: { ...noSess, train: null }, selfSid: 'self', columns: 80, expanded: false })
  expect(txt(nul[0])).toBe(' 작업  학습 2판 실행')
  const empty = buildBand({ work, server: { ...noSess, train: [] }, selfSid: 'self', columns: 80, expanded: false })
  expect(txt(empty[0])).toBe(' 작업  이상 없음')
  const both = buildBand({ work: { codex: [], grok: [], train: null }, server: { ...noSess, train: null }, selfSid: 'self', columns: 80, expanded: false })
  expect(txt(both[0])).toBe(' 작업  학습 (조회 실패)')
})

test('학습 판: 펼친 보기에 짧은 이름·?/60·last/없음만, 지표·최근 값·체크포인트 줄은 없다', async () => {
  for (const columns of [60, 80, 120]) {
    const rows = buildBand({ work: idle, server: withTrain, selfSid: 'self', columns, expanded: true })
    for (const r of rows) expect(lineWidth(r)).toBeLessThanOrEqual(columns - 4)
  }
  const rows = buildBand({ work: idle, server: withTrain, selfSid: 'self', columns: 240, expanded: true })
  const lines = LEFT(rows, 240)
  expect(lines[0]).toBe(' 작업')
  expect(lines[1]).toBe('학습 GPU3 x72-1t  ?/60  last')
  expect(lines[2]).toBe('     GPU4 x72t  ?/60  last 없음')   // 판마다 한 줄
  expect(allText(rows)).not.toMatch(/지표|체크포인트|val_score|e15/)
  expect(rows[1].find(s => s.text === 'last').tone).toBe('ok')   // 개정 26: 판 줄은 둘째 줄부터
  expect(rows[2].find(s => s.text === 'last 없음').tone).toBe('dim')
  expect(RIGHT(rows, 240)[0].startsWith(' 서버')).toBe(true)   // 첫 줄 오른쪽은 배지뿐이고 GPU 는 둘째 줄부터
  expect(RIGHT(rows, 240)[1].startsWith('GPU')).toBe(true)
})

test('학습 판: 펼친 보기의 종료 개수는 현재 저장소 기준으로 유지', async () => {
  const ended = { codex: [], grok: [], train: { running: [], ended: ['c'] } }
  const lines = LEFT(buildBand({ work: ended, server: withTrain, selfSid: 'self', columns: 120, expanded: true }), 120)
  expect(lines).toContain('     1판 종료')   // 개정 26: 들여쓰기 7칸이 없어져 «학습 » 폭 5칸
})

test('학습 정화: 제어 문자 이름·문자열 에폭·NaN 값·잘못된 체크포인트는 배제', async () => {
  const bad = { gpu: '3', name: 'x' + BAD + 'y', max_epochs: '60', metric: 'm' + BAD, last: 'yes',
    ckpts: [{ epoch: 1, value: NaN }, { epoch: '2', value: 0.1 }, { epoch: 3.5, value: 0.1 }, null, { epoch: 4, value: Infinity }, { epoch: 5, value: 0.5 }] }
  const s = sanitize({ ...server, train: [bad, 7] }, idle)
  expect(s.server.train).toEqual([{ gpu: null, name: 'xy', max_epochs: null, done: null, metric: 'm', last: false, watcher: null,
    ckpts: [{ epoch: 1, value: null }, { epoch: 4, value: null }, { epoch: 5, value: 0.5 }] }])
  expect(sanitize({ ...server, train: 'x' }, idle).server.train).toBe(null)
  expect(sanitize(server, idle).server.train).toBe(null)
  const many = { ...RUN_A, ckpts: Array.from({ length: 30 }, (_, i) => ({ epoch: i, value: i })) }
  const kept = sanitize({ train: [many] }, idle).server.train[0].ckpts
  expect(kept.length).toBe(20)
  expect(kept[19].epoch).toBe(29)
  const out = buildBand({ work: idle, server: { ...noSess, train: [bad] }, selfSid: 'self', columns: 120, expanded: true })
  expect(out.some(r => hasBad(r.map(g => g.text).join('')))).toBe(false)
})

test('학습 정화: 판은 16개까지, 이름은 60칸까지', async () => {
  const runs = Array.from({ length: 20 }, (_, i) => ({ ...RUN_B, gpu: i, name: 'n' + i }))
  expect(sanitize({ train: runs }, idle).server.train.length).toBe(16)
  const long = 'a'.repeat(70)
  expect(sanitize({ train: [{ ...RUN_B, name: long }] }, idle).server.train[0].name).toBe('a'.repeat(60))
  expect(sanitize({ ...server, train: [{ ...RUN_B, name: 5 }] }, idle).server.train[0].name).toBe('')
})

test('학습 판: 체크포인트 값은 정화돼 담기지만 펼친 보기에는 지표·체크포인트·지수 표기가 나오지 않는다(개정 15)', async () => {
  const vals = [1e-5, 0, 0.001, -2.5e-4, 123456, 99999]
  const run = { ...RUN_A, ckpts: vals.map((value, i) => ({ epoch: i + 1, value })) }
  expect(sanitize({ train: [run] }, idle).server.train[0].ckpts.map(c => c.value)).toEqual(vals)
  const text = LEFT(buildBand({ work: idle, server: { ...noSess, train: [run] }, selfSid: 'self', columns: 300, expanded: true }), 300).join('\n')
  expect(text).not.toMatch(/지표|체크포인트|val_score|e1 |1\.00e-5|최근/)
})

// view.js 시험용 가짜 el: 노드를 그대로 객체로 만든다.
const el = { Box: p => ({ t: 'Box', ...p }), Text: p => ({ t: 'Text', ...p }), Button: p => ({ t: 'Button', ...p }) }

// 공식 요소 표(mods reference «Elements»)의 Text props. 이 밖의 prop(flexShrink·key 등)을 넣으면
// 엔진이 «Text prop … is not allowed» 로 띠 전체를 거부하고 자기 그림을 그린다(2026-10-15 실측).
const TEXT_PROPS = new Set(['color', 'backgroundColor', 'bold', 'italic', 'underline', 'dimColor', 'inverse', 'wrap', 'children'])
const walk = (n, f) => { f(n); for (const c of n.children || []) if (c && typeof c === 'object') walk(c, f) }

test('view: Text 에는 허용된 prop 만 들어간다(접힘·상세 모두)', async () => {
  for (const expanded of [false, true]) {
    const work = { codex: [{ model: 'gpt-6.1-sol', effort: 'xhigh' }], grok: [], train: { running: ['a'], ended: [] } }
    const tree = toTree(el, buildBand({ work, server, selfSid: 'self', columns: 80, expanded }), () => {})
    walk(tree, n => {
      if (n.t !== 'Text') return
      for (const k of Object.keys(n)) if (k !== 't') expect(TEXT_PROPS.has(k)).toBe(true)
      for (const v of Object.values(n)) expect(v === undefined).toBe(false)
    })
  }
})

test('view: 버튼을 뺀 마지막 칸만 줄어들고(감싸는 Box) 버튼은 flexShrink 0', async () => {
  const rows = buildBand({ work: idle, server, selfSid: 'self', columns: 80, expanded: false })
  const tree = toTree(el, rows, () => {})
  const kids = tree.children[0].children
  const cells = kids.filter(k => k.t === 'Box' && k.children && k.children[0] && k.children[0].t === 'Text' && !String(k.key).startsWith('band-btn'))   // 버튼 사이 빈 칸(spacer)은 뺀다
  const last = cells[cells.length - 1]
  expect(last.flexShrink).toBe(1)
  expect(last.children[0].wrap).toBe('truncate-end')
  for (const c of cells.slice(0, -1)) expect(c.flexShrink).toBe(0)
  const wrap = kids[kids.length - 1]
  expect(wrap.t).toBe('Box')
  expect(wrap.flexShrink).toBe(0)
  expect(wrap.children[0].t).toBe('Button')
})

test('poll: wantsBand 는 확실히 없을 때만 false', async () => {
  expect(wantsBand(['terminal'])).toBe(true)
  expect(wantsBand([{ kind: 'desktop' }])).toBe(true)
  expect(wantsBand(['web', { kind: 'ide' }])).toBe(false)
  expect(wantsBand(undefined)).toBe(true) // 예외·알 수 없는 모양
  expect(wantsBand('terminal')).toBe(true)
  expect(wantsBand([])).toBe(true)
  expect(wantsBand(['web', 42])).toBe(true)
})

test('poll: 캐시 ts 가 60초 넘게 오래됐거나 미래면 버린다', async () => {
  const now = 1_000_000_000_000
  const t = now / 1000
  expect(validCache({ ts: t - 10 }, now) !== null).toBe(true)
  expect(validCache({ ts: t - 61 }, now)).toBe(null)
  expect(validCache({ ts: t + 61 }, now)).toBe(null)
  expect(validCache({ ts: 'x' }, now)).toBe(null)
  expect(validCache(null, now)).toBe(null)
})

test('poll: 마지막 시도가 15초 안이면 다시 부르지 않는다', async () => {
  const now = 1_000_000_000_000
  const t = now / 1000
  expect(needsCollect({ ts: t - 5 }, null, now)).toBe(false) // 캐시가 신선
  expect(needsCollect({ ts: t - 30 }, null, now)).toBe(true)
  expect(needsCollect({ ts: t - 30 }, { ts: t - 5 }, now)).toBe(false) // 방금 시도함(실패했어도)
  expect(needsCollect(null, { ts: t - 20 }, now)).toBe(true)
  expect(needsCollect(null, { ts: t + 3600 }, now)).toBe(true) // 미래 시도 기록은 무시
})

// ---- 파스텔 팔레트 · 배지 · 구분선(개정 9, 2026-10-16) ----
test('접힌 띠 80열: 배지 · │ · 학습 칸은 GPU 별 판 수, 권한 칸 없음', async () => {
  const sv = { ...noSess, train: [{ ...RUN_A, done: 17 }, { ...RUN_B, done: 9 }] }
  const work = { ...idle, blocks: 2 }
  const rows = buildBand({ work, server: sv, selfSid: 'self', columns: 80 + SHIFT, expanded: false })
  expect(txt(rows[0])).toBe(' 작업  학습 GPU3 1  GPU4 1 │ 차단 2')
  expect(rows[0].find(s => s.text === ' │ ').tone).toBe('sep')
  for (const r of rows) expect(lineWidth(r)).toBeLessThanOrEqual(76 + SHIFT)
  expect(txt(buildBand({ work: idle, server: sv, selfSid: 'self', columns: 80, expanded: false })[0])).not.toContain('권한')
  expect(buildBand({ work: idle, server: sv, selfSid: 'self', columns: 120, expanded: true }).map(txt).join('\n')).not.toContain('권한')
})

test('테마 판정: light 로 시작하면 밝은 팔레트, 그 밖은 어두운 팔레트', async () => {
  for (const [v, k] of [['dark', 'dark'], ['light', 'light'], ['light-daltonized', 'light'], ['dark-daltonized', 'dark'], ['auto', 'dark'], [undefined, 'dark'], [3, 'dark']]) {
    expect(themeKind(v)).toBe(k)
  }
  expect(PALETTES.dark.bg).toBe('#272A3A')
  expect(PALETTES.light.bg).toBe('#F2EFFA')
})

test('view: 띠 Box 는 팔레트 바탕과 좌우 여백 1칸, 배지는 제 바탕, 밝은 테마는 밝은 값', async () => {
  const rows = buildBand({ work: { ...idle, blocks: 2 }, server, selfSid: 'self', columns: 80, expanded: false })
  for (const theme of ['dark', 'light'] as const) {
    const tree = toTree(el, rows, theme)
    expect(tree.backgroundColor).toBe(PALETTES[theme].bg)
    expect(tree.paddingX).toBe(1)
    const texts: any[] = []
    walk(tree, n => { if (n.t === 'Text') texts.push(n) })
    const badge = texts.find(t => t.children[0] === ' 작업 ')
    expect(badge.backgroundColor).toBe(theme === 'dark' ? '#FFC4A3' : '#FFD2B8')
    expect(badge.bold).toBe(true)
    expect(texts.find(t => t.children[0] === ' 서버 ').backgroundColor).toBe(theme === 'dark' ? '#A9D8FF' : '#C2E2FF')
    expect(texts.every(t => typeof t.color === 'string')).toBe(true)
  }
  expect(toTree(el, rows, 'constructor').backgroundColor).toBe(PALETTES.dark.bg) // 모르는 테마는 어두운 팔레트
})

// 버튼 칩(2026-11-03): 접힘 · 펼침의 모든 띠 버튼은 글자 앞뒤 한 칸 여백과 테마별 배경색을 갖고, 버튼 사이 빈 칸은 띠 바탕이다. 눌림 라벨은 여백을 뗀 글자다.
test('view: 버튼은 칩(앞뒤 한 칸 여백 + 테마별 배경색), 사이 빈 칸은 띠 바탕, 라벨은 여백 없음', async () => {
  const chips = { dark: '#3a3a3a', light: '#dcdcdc' }
  for (const expanded of [false, true]) {
    const rows = buildBand({ work: idle, server, selfSid: 'self', columns: 200, expanded, news: '📰 뉴스 크게' })
    for (const theme of ['dark', 'light'] as const) {
      expect(PALETTES[theme].chip).toBe(chips[theme])
      const tree = toTree(el, rows, theme)
      const buttons: any[] = []
      walk(tree, n => { if (n.t === 'Button' && !String(n.key).startsWith('band-act-')) buttons.push(n) })   // 세션 줄의 [숨김] 류는 칩 여백 없이 배경색만(아래)
      const keys = expanded ? ['band-news', 'band-mobile', 'band-mask', 'band-big', 'band-toggle'] : ['band-news-toggle', 'band-mobile', 'band-mask', 'band-toggle']
      expect(buttons.map(b => b.key)).toEqual(keys)
      for (const b of buttons) {
        const t = b.children[0]
        expect(t.children[0]).toBe(` ${b.label} `)                     // 글자 앞뒤 한 칸
        expect(t.backgroundColor).toBe(chips[theme])
        expect(t.backgroundColor).not.toBe(PALETTES[theme].bg)
        expect(b.label).toBe(b.label.trim())
      }
      const gaps: any[] = []
      walk(tree, n => { if (n.t === 'Text' && /^ +$/.test(n.children[0]) && String(n.backgroundColor) === PALETTES[theme].bg) gaps.push(n) })
      expect(gaps.length).toBeGreaterThanOrEqual(keys.length - 1)     // 칩 사이 빈 칸은 바탕색
      const acts: any[] = []
      walk(tree, n => { if (n.t === 'Button' && String(n.key).startsWith('band-act-')) acts.push(n) })
      for (const a of acts) expect(a.children[0].backgroundColor).toBe(chips[theme])   // [숨김] [제거] 도 같은 칩 배경(표 폭 때문에 여백은 없다)
    }
  }
})

// ---- 와쳐 · 세션별 작업(개정 11, 2026-10-16) ----
const watched = { ...noSess, train: [{ ...RUN_A, done: 17, watcher: true }, { ...RUN_B, done: 9, watcher: false }] }

test('와쳐: 접힌 띠는 살아 있으면 ◉(민트) · 없으면 와쳐✗(분홍) · launch-set 판이 아니면 표시 없음', async () => {
  const rows = buildBand({ work: idle, server: watched, selfSid: 'self', columns: 80 + SHIFT, expanded: false })
  expect(txt(rows[0])).toBe(' 작업  학습 GPU3 1 ◉  GPU4 1 와쳐✗')
  expect(rows[0].find(s => s.text === ' ◉').tone).toBe('ok')
  expect(rows[0].find(s => s.text === ' 와쳐✗').tone).toBe('hot')
  expect(txt(buildBand({ work: idle, server: withDone, selfSid: 'self', columns: 80 + SHIFT, expanded: false })[0]))
    .toBe(' 작업  학습 GPU3 1  GPU4 1')   // watcher null 은 표시 없음
  for (const r of rows) expect(lineWidth(r)).toBeLessThanOrEqual(76 + SHIFT)
})

test('와쳐: 사다리에서 ◉ 는 빠져도 와쳐 없음 경보(✗)는 끝까지 남는다', async () => {
  const at = (columns: number) => buildBand({ work: idle, server: watched, selfSid: 'self', columns: columns + EXTRA, expanded: false })[0]
  expect(txt(at(58))).toBe(' 작업  학습 GPU3 1 ◉  GPU4 1 와쳐✗')
  expect(txt(at(42))).toBe(' 작업  학습 GPU3 1 ◉  GPU4 1 ✗')             // 3단계: 와쳐✗ → ✗
  expect(txt(at(34))).toBe(' 작업  학습 실행2 ✗')                          // 개수만 남는 단계: ◉ 는 빠지고 ✗ 경보만
  expect(txt(at(34))).not.toContain('◉')
  for (const columns of [34, 42, 46, 58, 80]) {
    const r = at(columns)
    expect(r.some(s => s.tone === 'hot' && s.text.includes('✗'))).toBe(true)
    expect(lineWidth(r.filter(s => !s.button))).toBeLessThanOrEqual(columns - 4 - 7)
  }
  const ok = buildBand({ work: idle, server: { ...noSess, train: [{ ...RUN_A, watcher: true }, { ...RUN_B, watcher: true }] }, selfSid: 'self', columns: 30 + EXTRA, expanded: false })[0]
  expect(txt(ok)).toBe(' 작업  학습 실행2')                              // 살아 있는 와쳐(◉)는 개수만 남는 단계에서 빠진다
})

test('와쳐: 펼친 보기는 판 줄(에폭 뒤, last 앞)에 와쳐/없음, null 이면 와쳐 표시만 없다', async () => {
  const rows = buildBand({ work: idle, server: watched, selfSid: 'self', columns: 240, expanded: true })
  const lines = LEFT(rows, 240)
  expect(lines[1]).toBe('학습 GPU3 x72-1t  17/60  와쳐  last')   // 개정 26: 판 줄은 둘째 줄부터
  expect(lines[2]).toBe('     GPU4 x72t  9/60  와쳐 없음  last 없음')
  expect(rows[1].find(s => s.text === '와쳐').tone).toBe('ok')
  expect(rows[2].find(s => s.text === '와쳐 없음').tone).toBe('hot')
  const nul = LEFT(buildBand({ work: idle, server: withDone, selfSid: 'self', columns: 240, expanded: true }), 240).join('\n')
  expect(nul).not.toContain('와쳐')
  expect(nul).toContain('last')   // 와쳐가 null 이어도 last 유무는 둔다
})

test('와쳐 정화: true/false 만 받고 그 밖은 null', async () => {
  const w = v => sanitize({ ...server, train: [{ ...RUN_B, watcher: v }] }, idle).server.train[0].watcher
  expect([w(true), w(false)]).toEqual([true, false])
  for (const bad of ['true', 1, 0, null, undefined, {}]) expect(w(bad)).toBe(null)
})

// ---- 같은 GPU 묶음(개정 13, 2026-10-17): 접힌 띠는 판 이름 없이 GPU 별 `GPU3 (17/9)/60`, 펼친 보기는 판마다 GPU 라벨 반복 ----
const RUN_A2 = { ...RUN_B, gpu: 3, name: 'exp-demo-1b-x72t-2', done: 9 }
const RUN_A3 = { ...RUN_B, gpu: 3, name: 'exp-demo-1b-x72t-3', done: 5 }
const grouped = { ...noSess, train: [{ ...RUN_A, done: 17 }, RUN_A2, { ...RUN_B, done: 9 }] }
const col = (sv, columns: number, expanded = false) => buildBand({ work: idle, server: sv, selfSid: 'self', columns, expanded })

test('같은 GPU 묶음: 접힌 띠는 GPU 별 판 수만(두 판 GPU3 2 · 세 판 GPU3 3 · 한 판 GPU4 1), 실행N 은 판 개수', async () => {
  expect(txt(col(grouped, 80)[0])).toBe(' 작업  학습 GPU3 2  GPU4 1')
  const three = { ...noSess, train: [{ ...RUN_A, done: 1 }, { ...RUN_A2, done: 3 }, { ...RUN_A3, done: 5 }, { ...RUN_B, done: 9 }] }
  expect(txt(col(three, 80)[0])).toBe(' 작업  학습 GPU3 3  GPU4 1')
  const at = (columns: number) => txt(col(grouped, columns)[0])
  expect(at(64)).toBe(' 작업  학습 GPU3 2  GPU4 1')   // 한 판뿐인 GPU4 도 GPU 접두를 떼지 않는다
  expect(at(30 + NARROW)).toBe(' 작업  학습 실행3')
  const unknown = { ...noSess, train: [{ ...RUN_A, gpu: null, done: 17 }, { ...RUN_A2, gpu: null }] } // gpu 를 모르는 판은 각각 따로
  expect(txt(col(unknown, 80)[0])).toBe(' 작업  학습 GPU? 1  GPU? 1')
})

test('접힌 띠: 한 GPU 에 세 판이면 GPU5 3, 판 이름·에폭은 없다', async () => {
  const on5 = (name: string, done: number) => ({ ...RUN_B, gpu: 5, name, done })
  const sv = { ...noSess, train: [on5('exp-demo-1b-x1t', 3), on5('exp-demo-1b-x2t', 4), on5('exp-demo-1b-x3t', 5)] }
  const row = col(sv, 80)[0]
  expect(txt(row)).toBe(' 작업  학습 GPU5 3')
  expect(txt(row)).not.toMatch(/x1t|\/60/)
  expect(txt(col({ ...sv, train: [...sv.train, { ...RUN_A, done: 1 }] }, 80)[0])).toBe(' 작업  학습 GPU5 3  GPU3 1')   // 묶음은 GPU 별, 순서는 입력 순서
})

test('같은 GPU 묶음 와쳐: 한 판만 false 면 와쳐✗, 전부 true 면 ◉, null 과 true 가 섞이면 ◉, 실행N 의 ✗ 규칙은 그대로', async () => {
  const w = (a, b) => ({ ...noSess, train: [{ ...RUN_A, done: 17, watcher: a }, { ...RUN_A2, watcher: b }] })
  const t = (a, b, columns = 80) => col(w(a, b), columns)[0]
  expect(txt(t(true, false))).toBe(' 작업  학습 GPU3 2 와쳐✗')
  expect(t(true, false).find(s => s.text === ' 와쳐✗').tone).toBe('hot')
  expect(txt(t(true, false, 32 + NARROW))).toBe(' 작업  학습 GPU3 2 ✗')   // 좁은 열
  expect(txt(t(true, true))).toBe(' 작업  학습 GPU3 2 ◉')
  expect(t(true, true).find(s => s.text === ' ◉').tone).toBe('ok')
  expect(txt(t(null, true))).toContain(' ◉')
  expect(txt(t(null, null))).not.toMatch(/◉|✗/)
  expect(txt(t(false, true, 30 + NARROW))).toBe(' 작업  학습 실행2 ✗')   // 가장 좁은 단계: 실행N 에 ✗ 경보만 남는다
  expect(txt(t(true, true, 30 + NARROW))).toBe(' 작업  학습 실행2')
})

// 실제 이름(shortName 으로 x72-1t 꼴)을 쓴다. 판 줄은 120열 왼쪽 반(56칸)에 «와쳐 …  last …» 까지 한 줄에 들어간다.
const SHORT_A = { ...RUN_A, metric: '', done: 17, watcher: false, last: false, ckpts: [{ epoch: 5, value: -0.3136 }] }
const SHORT_B = { ...RUN_A2, watcher: true, last: true }
const SHORT_C = { ...RUN_B, done: 2, watcher: false, last: true }

test('같은 GPU 묶음: 펼친 보기는 트리 없이 판마다 한 줄 «GPU3 a72-…» 이고 120열 왼쪽 반에서 와쳐 없음·last 없음이 보인다', async () => {
  const sv = { ...noSess, train: [SHORT_A, SHORT_B, SHORT_C] }
  for (const columns of [60, 80, 120]) for (const r of col(sv, columns, true)) expect(lineWidth(r)).toBeLessThanOrEqual(columns - 4)
  const rows = col(sv, 120, true)
  const lines = LEFT(rows, 120)
  expect(lines[1]).toBe('학습 GPU3 x72-1t  17/60  와쳐 없음  last 없음')   // 개정 26: 판 줄은 둘째 줄부터
  expect(lines[2]).toBe('     GPU3 x72t-2  9/60  와쳐  last')
  expect(lines[3]).toBe('     GPU4 x72t  2/60  와쳐 없음  last')
  expect(lines.join('\n')).not.toMatch(/ㄴ|체크포인트|지표/)
  expect(rows[1].find(s => s.text === '와쳐 없음').tone).toBe('hot')
  expect(rows[1].find(s => s.text === 'last 없음').tone).toBe('dim')
  expect(rows[2].find(s => s.text === 'last').tone).toBe('ok')
  // 지표가 있는 판도 지표는 나오지 않고 판 줄은 그대로다
  const withMetric = LEFT(col({ ...noSess, train: [{ ...RUN_A, done: 17, watcher: false, last: false }] }, 120, true), 120)[1]
  expect(withMetric).toBe('학습 GPU3 x72-1t  17/60  와쳐 없음  last 없음')
  // 와쳐가 null(launch-set 판 아님)이어도 last 유무는 둔다
  const nul = LEFT(col({ ...noSess, train: [{ ...SHORT_A, watcher: null }] }, 120, true), 120)[1]
  expect(nul).toBe('학습 GPU3 x72-1t  17/60  last 없음')
})

test('같은 GPU 묶음: 좁은 열에서도 «GPU3» 을 유지하고 모든 열이 줄 폭 한도 안', async () => {
  const only = { ...noSess, train: [{ ...RUN_A, done: 17, watcher: false }, { ...RUN_A2, watcher: true }] }
  for (const columns of [34, 42, 50, 58, 80]) {
    expect(txt(col(only, columns + EXTRA)[0])).toContain('GPU3')
    for (const sv of [grouped, only]) expect(lineWidth(col(sv, columns + EXTRA)[0].filter(s => !s.button))).toBeLessThanOrEqual(columns - 4 - 7)
  }
  expect(txt(col(only, 34 + EXTRA)[0])).toBe(' 작업  학습 GPU3 2 ✗')
})

test('펼친 보기 좌우 분할: 80열·120열 모두 왼쪽 작업 · 오른쪽 서버, │ 구분, 모든 줄이 한도 안', async () => {
  const work = { codex: [{ model: 'gpt-6.1-sol', effort: 'xhigh' }], grok: [], train: { running: [], ended: [] } }
  for (const columns of [80, 120]) {
    const rows = buildBand({ work, server: { ...server, train: [SHORT_A] }, selfSid: 'self', columns, expanded: true })
    const limit = columns - 4
    for (const r of rows) expect(lineWidth(r)).toBeLessThanOrEqual(limit)
    expect(lineWidth(rows[0].filter(s => !s.button))).toBeLessThanOrEqual(limit - lineWidth(rows[0].filter(s => s.button)))   // 버튼 자리를 뺀 폭
    // 80열은 오른쪽 반(36칸)이 모자라 모바일이 빠지고, 120열은 4개 모두(DETAIL_BTN_RESERVE = 뉴스 없는 전체 폭)
    expect(rows[0].filter(s => s.button && !s.spacer).map(s => s.key)).toEqual(columns === 80 ? ['band-mask', 'band-big', 'band-toggle'] : ['band-mobile', 'band-mask', 'band-big', 'band-toggle'])
    expect(lineWidth(rows[0].filter(s => s.button))).toBeLessThanOrEqual(DETAIL_BTN_RESERVE)
    const [l, r] = halves(rows[0], columns)
    expect(l).toBe(' 작업')   // 개정 26: 첫 줄 왼쪽은 배지뿐(halves 가 뒤 공백을 지운다)
    expect(rows[0][0]).toEqual({ text: ' 작업 ', tone: 'workBadge' })   // 배지 글자는 앞뒤 공백 그대로(qa 2026-10-23)
    expect(r.startsWith(' 서버 ')).toBe(columns !== 80)   // 80열은 칩 버튼 3개가 오른쪽 반(36칸)을 채워 배지가 빠진다(버튼이 먼저)
    expect(l).not.toContain(' 서버 ')
    expect(rows[0].filter(s => s.text === ' │ ' && s.tone === 'sep').length).toBeGreaterThanOrEqual(1)
    // 줄 수가 달라도 모든 줄에 구분선이 있고, 구분선 앞은 같은 칸 수(colW)다
    const colW = Math.floor((limit - 3) / 2)
    for (const row of rows) {
      const cells = row.filter(s => !s.button), k = cells.findIndex((s, i) => s.text === ' │ ' && lineWidth(cells.slice(0, i)) === colW)
      expect(k).toBeGreaterThan(0)
    }
    // 서버 쪽 GPU·여유 줄은 오른쪽 반에만 있고 GPU 6장이 모두 보인다
    const right = RIGHT(rows, columns).join('\n')
    for (const g of ['0 0% 0/45G', '3 96% 26/80G', '5 0% 0/45G']) expect(right).toContain(g)
    expect(right).toContain('여유')
    expect(LEFT(rows, columns).join('\n')).not.toMatch(/GPU 0|여유/)
  }
})

const JOBS = [
  { sid: 'self', name: '[Harness] Manager', status: 'shell', job_state: 'working', job_detail: '하네스 띠 반영' },
  { sid: 'b', name: '[PRJ] Manager', status: 'shell', job_state: 'working', job_detail: 'run_exp.py 추론 결과 확인' },
  { sid: 'c', name: '[PRJ] 2.0.0', status: 'shell', job_state: 'needs_input', job_detail: '승인 대기' },
  { sid: 'd', name: '[Research] Lab', status: 'shell', job_state: 'done', job_detail: null },
  { sid: 'e', name: '[A] Old', status: 'busy', job_state: null, job_detail: null },
  { sid: 'f', name: '[B] Broken', status: 'shell', job_state: 'failed', job_detail: '실패 원인' }]
const withJobs = { ...noSess, sessions: JOBS }

test('세션 칸: job_state 로 분류(작업 중 ● · 입력 대기 ◐ · 끝남 ○ · 실패 ✗ 분홍), 없으면 status, 본인은 뺀다', async () => {
  const rows = buildBand({ work: idle, server: withJobs, selfSid: 'self', columns: 120, expanded: false })
  expect(txt(rows[0])).toBe(' 작업  이상 없음 │ 세션 ●2 ○1 ◐1 ✗1')   // b(작업 중)+e(status busy) · d · c · f
  expect(rows[0].find(s => s.text === '✗1').tone).toBe('hot')
  expect(rows[0].find(s => s.text === '◐1').tone).toBe('warn')
  expect(txt(rows[1])).not.toContain('세션')
  // job_state 가 status 보다 우선: status idle 이어도 working 이면 ●, status busy 여도 done 이면 ○
  const mixed = [{ sid: 'x', name: 'x', status: 'idle', job_state: 'working', job_detail: null }, { sid: 'y', name: 'y', status: 'busy', job_state: 'done', job_detail: null }]
  expect(txt(buildBand({ work: idle, server: { ...noSess, sessions: mixed }, selfSid: 'self', columns: 120, expanded: false })[0])).toContain('세션 ●1 ○1')
  // 본인뿐이면 세션 칸 자체가 없다
  expect(txt(buildBand({ work: idle, server: { ...noSess, sessions: [JOBS[0]] }, selfSid: 'self', columns: 120, expanded: false })[0])).toBe(' 작업  이상 없음')
})

test('세션 칸: 학습·차단 칸 뒤에 놓이고 좁으면 마지막 단계에서 숨는다', async () => {
  const work = { codex: [{ model: 'gpt-6.1-sol', effort: 'xhigh' }], grok: [{ model: 'grok-4.7', effort: 'high' }], train: { running: ['a'], ended: [] }, blocks: 2 }
  const row = buildBand({ work, server: { ...withJobs, train: [{ ...RUN_A, done: 17, watcher: true }] }, selfSid: 'self', columns: 120, expanded: false })[0]
  expect(txt(row)).toMatch(/학습 .* │ 차단 2 │ 세션 ●2 ○1 ◐1 ✗1$/)
  const workB = { ...idle, blocks: 2 }
  const narrow = buildBand({ work: workB, server: { ...withJobs, train: [{ ...RUN_A, watcher: false }, { ...RUN_B, watcher: false }] }, selfSid: 'self', columns: 36 + EXTRA, expanded: false })[0]
  expect(txt(narrow)).not.toContain('세션')
  expect(txt(narrow)).toContain('실행2 ✗')                                // 세션이 숨어도 와쳐 없음 경보는 남는다
  expect(lineWidth(narrow.filter(s => !s.button))).toBeLessThanOrEqual(36 - 4 - 7)
})

const sp = (n: number) => ' '.repeat(n)
test('펼친 세션 줄: 표(머리 줄 · 버튼 · 이름 · 상태 · 활동 열 맞춤)·본인 표시·순서(본인 → 작업 중 → 입력 대기 → 나머지 이름순)', async () => {
  const rows = buildBand({ work: idle, server: withJobs, selfSid: 'self', columns: 160, expanded: true })   // 반 폭 76: 세션 표가 잘리지 않는다
  const lines = LEFT(rows, 160)
  const from = lines.findIndex(l => l.includes('세션'))
  expect(lines[from - 1].trim()).toBe('')   // 학습 묶음과 세션 표 사이 빈 줄(개정 21)
  const sess = lines.slice(from, from + 7)
  expect(sess).toEqual([   // 개정 21: 머리 줄의 버튼 칸 자리에 «세션», 열은 같은 폭(이름 18 = 가장 긴 이름, 상태 9 = «입력 대기»)
    '세션' + sp(12) + '이름' + sp(16) + '상태' + sp(7) + '활동',   // 개정 26: 표 앞 들여쓰기 7칸이 없다
    sp(14) + '● [Harness] Manager*  작업 중    하네스 띠 반영',
    '[숨김]' + sp(8) + '● [A] Old' + sp(13) + '작업 중', // 잡이 없는 세션의 status 도 한글 글자로(busy → 작업 중), [제거] 자리는 공백
    '[숨김]' + sp(8) + '● [PRJ] Manager' + sp(7) + '작업 중    run_exp.py 추론 결과 확인',   // 개정 26: 왼쪽 반이 7칸 넓어져 160열에서 활동이 잘리지 않는다
    '[숨김]' + sp(8) + '◐ [PRJ] 2.0.0' + sp(9) + '입력 대기  승인 대기',
    '[숨김]' + sp(8) + '✗ [B] Broken' + sp(10) + '실패' + sp(7) + '실패 원인',
    '[숨김]' + sp(8) + '○ [Research] Lab' + sp(6) + '끝남'])
  const seg = (r: number, t: string) => rows[from + r].find(s => s.text.trim() === t)
  expect(seg(0, '세션').tone).toBe('label')
  expect(seg(1, '[Harness] Manager*').tone).toBe('self')            // 본인은 굵게 + *
  expect(seg(4, '입력 대기').tone).toBe('warn')
  expect(seg(5, '실패').tone).toBe('hot')
  expect(seg(6, '[Research] Lab').tone).toBe('dim')
  expect(RIGHT(rows, 160).some(l => l.includes('세션'))).toBe(false)   // 서버(오른쪽) 부분에는 세션 줄이 없다
  expect(RIGHT(rows, 160)[0].startsWith(' 서버')).toBe(true)
  for (const r of rows) expect(lineWidth(r)).toBeLessThanOrEqual(156)
})

// ---- 개정 20(2026-10-23 사용자 결정): 세션 숨김·제거 버튼, 높이 창, 접기 고정 ----
const RM = [
  { sid: 'self', name: '[Harness] Manager', status: 'busy', job: '0a1b2c3d', job_state: 'working', job_detail: null },
  { sid: 's-idle', name: '9e0b4934', status: 'idle', job: '9e0b4934', job_state: null, job_detail: null },
  { sid: 's-busy', name: '[PRJ] 2.0.0', status: 'busy', job: 'dfcc02d6', job_state: 'working', job_detail: null },
  { sid: 's-nojob', name: 'nojob', status: 'idle', job: 'NOT-HEX', job_state: null, job_detail: null }]
const acts = rows => rows.flat().filter(s => s.act).map(s => `${s.act}:${s.sid}`)

test('세션 줄 버튼: 본인 없음 · 숨김은 모두 · 제거는 잡 id 가 있고 작업 중이 아닌 세션만', async () => {
  const rows = buildBand({ work: idle, server: { ...noSess, sessions: RM }, selfSid: 'self', columns: 160, expanded: true })
  const a = acts(rows)
  expect(a).not.toContain('hide:self')
  expect(a).toContain('hide:s-idle')
  expect(a).toContain('rm:s-idle')
  expect(a).toContain('hide:s-busy')
  expect(a).not.toContain('rm:s-busy')       // 작업 중
  expect(a).not.toContain('rm:s-nojob')      // 잡 id 형식이 아님(정화에서 null)
  for (const r of rows) expect(lineWidth(r)).toBeLessThanOrEqual(156)
  // 허용 목록(security 2026-10-23): 쉬는 중(idle)만 · 잡 id 를 다른 세션과 같이 쓰면 없음
  const more = [...RM, { sid: 's-shell', name: 'sh', status: 'shell', job: 'aaaaaaaa', job_state: 'done', job_detail: null },
    { sid: 's-dup1', name: 'd1', status: 'idle', job: 'bbbbbbbb', job_state: null, job_detail: null },
    { sid: 's-dup2', name: 'd2', status: 'idle', job: 'bbbbbbbb', job_state: null, job_detail: null }]
  const b = acts(buildBand({ work: idle, server: { ...noSess, sessions: more }, selfSid: 'self', columns: 160, expanded: true }))
  expect(b).not.toContain('rm:s-shell')
  expect(b).not.toContain('rm:s-dup1')
  expect(b).not.toContain('rm:s-dup2')
  expect(b).toContain('rm:s-idle')
})

test('세션 숨김: 숨긴 세션은 펼친 줄·접힌 개수에서 빠지고 «숨김 N [되돌리기]» 가 붙는다(본인은 숨기지 않는다)', async () => {
  const hidden = new Set(['s-idle', 'self'])
  const rows = buildBand({ work: idle, server: { ...noSess, sessions: RM }, selfSid: 'self', columns: 160, expanded: true, hidden })
  const left = LEFT(rows, 160).join('\n')
  expect(left).not.toContain('9e0b4934')
  expect(left).toContain('[Harness] Manager*')
  expect(left).toContain('[되돌리기] 숨긴 세션 1')
  expect(acts(rows)).toContain('unhide:all')
  const folded = buildBand({ work: idle, server: { ...noSess, sessions: RM }, selfSid: 'self', columns: 160, expanded: false, hidden })
  expect(txt(folded[0])).toContain('세션 ●1 ○1')   // s-busy(작업 중) · s-nojob(쉼), s-idle 은 빠짐
})

test('세션 제거 확정: confirmSid 줄만 «제거할까요? [확정] [취소]» 로 바뀐다', async () => {
  const rows = buildBand({ work: idle, server: { ...noSess, sessions: RM }, selfSid: 'self', columns: 160, expanded: true, confirmSid: 's-idle' })
  const a = acts(rows)
  expect(a).toContain('rmok:s-idle')
  expect(a).toContain('cancel:s-idle')
  expect(a).not.toContain('rm:s-idle')
  expect(a).toContain('hide:s-busy')         // 다른 줄은 그대로
  const line = LEFT(rows, 160).find(l => l.includes('[확정] [취소] ○ 9e0b4934'))
  expect(line).toBeDefined()
  expect(line).toMatch(/제거할까요\? 잡 9e0b4934$/)   // 확정 대기 줄의 활동 칸: 지울 잡 id 를 같이 보인다(security 2026-10-23)
  // 활동 열이 들어가지 않을 만큼 좁으면 «제거할까요?» 는 빠지고 [확정] [취소] 버튼만 남는다
  const narrow = buildBand({ work: idle, server: { ...noSess, sessions: RM }, selfSid: 'self', columns: 80, expanded: true, confirmSid: 's-idle' })
  expect(acts(narrow)).toContain('rmok:s-idle')
  for (const r of narrow) expect(lineWidth(r)).toBeLessThanOrEqual(76)
})

test('windowBand: 첫 줄 고정 · 지정 높이(조절 줄 포함) · 넘김 위치 자르기 · 자동 높이 · 상한', async () => {
  const rows = Array.from({ length: 20 }, (_, i) => [{ text: 'r' + i, tone: 'base' }, { text: ' │ ', tone: 'sep', divider: true }])
  const w = windowBand(rows, { height: 8, offset: 3, maxRows: 30 })
  expect(w.height).toBe(8)
  expect(w.rows.length).toBe(7)                       // 조절 줄 1 + 첫 줄 1 + 창 6 = 8 중 띠 줄은 7
  expect(w.rows[0][0].text).toBe('r0')                // 첫 줄(접기 버튼 줄)은 넘겨도 고정
  expect(w.rows[1][0].text).toBe('r4')                // body 는 offset 3 부터(r1 이 body 0)
  expect(w.maxOffset).toBe(19 - 6)
  expect(windowBand(rows, { height: 8, offset: 999, maxRows: 30 }).offset).toBe(13)   // 끝을 넘으면 끝
  expect(windowBand(rows, { height: 8, offset: -5, maxRows: 30 }).offset).toBe(0)
  expect(windowBand(rows, { height: 100, maxRows: 15 }).height).toBe(15)              // 엔진 상한
  expect(windowBand(rows, { height: 1, maxRows: 15 }).height).toBe(4)                 // 최소 4줄
  const auto = windowBand(rows.slice(0, 3), { height: 0, maxRows: 30 })
  expect(auto.auto).toBe(true)
  expect(auto.height).toBe(4)                         // 내용 3줄 + 조절 줄
  const big = windowBand(rows.slice(0, 3), { height: 10, maxRows: 30 })
  expect(big.rows.length).toBe(9)                     // 내용보다 크면 빈 줄로 채워 그 높이를 덮는다
  for (const r of big.rows) expect(r.some(s => s.divider)).toBe(true)   // 빈 줄도 경계 칸을 갖는다(세 칸 배치 유지)
})

test('windowBand: 상한이 4줄보다 낮아도 트리가 상한을 넘지 않고(3줄 미만이면 조절 줄 없음) 첫 줄은 남는다', async () => {
  const rows = Array.from({ length: 10 }, (_, i) => [{ text: 'r' + i, tone: 'base' }, { text: ' │ ', tone: 'sep', divider: true }])
  for (const cap of [1, 2, 3, 4]) {
    const w = windowBand(rows, { height: 8, maxRows: cap })
    expect(w.rows.length + (w.handle ? 1 : 0)).toBeLessThanOrEqual(cap)
    expect(w.rows[0][0].text).toBe('r0')
  }
  expect(windowBand(rows, { height: 8, maxRows: 2 }).handle).toBe(false)
})

test('treeRows: 세로 Box 는 합, 가로 Box 는 최대, Text 는 1 + 줄바꿈 수', async () => {
  const T = (s: string) => ({ type: 'Text', props: {}, children: [s] })
  expect(treeRows(T('drawn by Claude Code'))).toBe(1)
  expect(treeRows(T('a\nb\nc'))).toBe(3)
  expect(treeRows({ type: 'Box', props: { flexDirection: 'column' }, children: [T('a'), T('b')] })).toBe(2)
  expect(treeRows({ type: 'Box', props: { flexDirection: 'row' }, children: [T('a'), T('b\nc')] })).toBe(2)
  expect(treeRows(null)).toBe(0)
})

test('view toTree: 높이 창이 있으면 맨 위에 height.js 조절 줄, Client 없는 화면은 글자 한 줄', async () => {
  const rows = buildBand({ work: idle, server, selfSid: 'self', columns: 120, expanded: true })
  const w = windowBand(rows, { height: 6, offset: 1, maxRows: 20 })
  const withClient = { ...el, Client: p => ({ t: 'Client', ...p }) }
  const tree = toTree(withClient, w.rows, 'dark', 0, w, 120)
  expect(tree.flexDirection).toBe('column')
  expect(tree.children[0].key).toBe('band-height')
  expect(tree.children[0].module).toMatch(/height\.js$/)
  expect(tree.children[0].props.height).toBe(6)
  expect(tree.children[0].props.label).toContain('높이 6줄')
  expect(tree.children[1].key).toBe('band-body')
  const plain = toTree(el, w.rows, 'dark', 0, w, 120)
  expect(plain.children[0].key).toBe('band-height-text')
  const auto = windowBand(rows, { height: 0, maxRows: 40 })
  expect(toTree(withClient, auto.rows, 'dark', 0, auto, 120).children[0].props.label).toContain('높이 자동')
})

test('크게(개정 21): 창이 아니라 띠 높이를 이 세션 최대로, 버튼 글자는 크게 ⇱ ↔ 작게 ⇲', async () => {
  const btn = (big: boolean) => buildBand({ work: idle, server: { ...noSess, sessions: RM }, selfSid: 'self', columns: 140, expanded: true, big })[0]
    .find(s => s.button && s.key === 'band-big')
  expect(btn(false).text).toBe(' 크게 ⇱ ')   // 칩: 글자 앞뒤 한 칸 여백
  expect(btn(true).text).toBe(' 작게 ⇲ ')
  const rows = Array.from({ length: 40 }, (_, i) => [{ text: 'r' + i, tone: 'base' }, { text: ' │ ', tone: 'sep', divider: true }])
  const w = windowBand(rows, { height: BIG_HEIGHT, maxRows: 17 })
  expect(w.height).toBe(17)                  // 상한(이 세션 지금 최대 높이)까지
  expect(w.big).toBe(true)
  expect(w.cap).toBe(17)
  expect(windowBand(rows, { height: 8, maxRows: 17 }).big).toBe(false)
  expect(windowBand(rows.slice(0, 3), { height: BIG_HEIGHT, maxRows: 17 }).rows.length).toBe(16)   // 내용이 적어도 최대 높이를 덮는다(조절 줄 1 + 16)
})

test('세션 표 검수 반영(개정 21): 본인 «*» 는 잘려도 남고, 보일 세션이 없으면 표가 없고, 아주 좁으면 버튼 칸을 통째로 뺀다', async () => {
  const left80 = LEFT(buildBand({ work: idle, server, selfSid: 'self', columns: 64, expanded: true }), 64).join('\n')   // 개정 26: 들여쓰기 7칸이 빠져 80열에서는 이름이 잘리지 않아 잘리는 경계가 64열로 내려갔다
  expect(left80).toMatch(/\[Harness\][^\n]*…\*/)                  // «[Harness] …*»
  const none = LEFT(buildBand({ work: idle, server: noSess, selfSid: 'self', columns: 120, expanded: true }), 120)
  expect(none.some(l => l.includes('세션'))).toBe(false)
  expect(none.filter(l => l.trim() === '').length).toBe(none.length - 2)   // 개정 26: 배지 줄(' 작업')과 «이상 없음» 줄 말고는 오른쪽 반 높이에 맞춘 빈 줄뿐
  for (const columns of [40, 44, 50, 56]) {
    const rows = buildBand({ work: idle, server: { ...noSess, sessions: RM }, selfSid: 'self', columns, expanded: true })
    for (const r of rows) expect(lineWidth(r)).toBeLessThanOrEqual(columns - 4)
    const labels = rows.flat().filter(s => s.act).map(s => s.text)
    expect(labels.every(t => ['[숨김]', '[제거]', '[확정]', '[취소]', '[되돌리기]'].includes(t))).toBe(true)   // 잘린 버튼 글자 없음
  }
})

test('상한 진단(개정 21-1): treeTexts 는 Text 글자를 앞에서부터 모으고, 라벨은 다른 그림이 있을 때만 내역을 보인다', async () => {
  const T = (s: string) => ({ type: 'Text', props: {}, children: [s] })
  const tree = { type: 'Box', props: { flexDirection: 'column' }, children: [T('할 일 1'), { type: 'Box', props: {}, children: [T('  '), T('할 일 2' + 'x'.repeat(80))] }] }
  const got = treeTexts(tree)
  expect(got[0]).toBe('할 일 1')
  expect(got[1].length).toBe(60)
  expect(treeTexts(null)).toEqual([])
  const rows = buildBand({ work: idle, server, selfSid: 'self', columns: 120, expanded: true })
  const withClient = { ...el, Client: p => ({ t: 'Client', ...p }) }
  // 개정 23·24: 상한은 엔진이 띠에 보여 주는 줄 수, 전체 화면 방식이면 괄호에 «세션 창의 절반» 만 붙인다
  const w = { ...windowBand(rows, { height: 10, maxRows: 14 }), fullscreen: true, termRows: 46 }
  expect(toTree(withClient, w.rows, 'dark', 0, w, 120).children[0].props.label).toContain('높이 10줄 · 상한 14줄(세션 창의 절반) · ')
  const w0 = { ...windowBand(rows, { height: 0, maxRows: 40 }), termRows: 46 }
  expect(toTree(withClient, w0.rows, 'dark', 0, w0, 120).children[0].props.label).not.toContain('전체 화면')
})

const TODOS = { done: 32, doing: 2, open: 2, items: [{ state: 'doing', subject: '스크래치 스캔' }, { state: 'doing', subject: 'A-0781 원인' }, { state: 'open', subject: 'zip 여부 묻기' }, { state: 'open', subject: 'cap 빈틈' + ch(0x202e) }] }
test('할 일(개정 22·23): 접힌 띠는 «할 일 완료32 진행2 남음2», 펼친 보기는 개수 줄 + [펼치기], 펼치면 진행 → 남음 항목', async () => {
  const work = { ...idle, todos: TODOS }
  const folded = buildBand({ work, server: noSess, selfSid: 'self', columns: 120, expanded: false })
  expect(txt(folded[0])).toBe(' 작업  이상 없음 │ 할 일 완료32 진행2 남음2')
  for (const s of [...folded[0], ...buildBand({ work, server: noSess, selfSid: 'self', columns: 160, expanded: true, todosOpen: true }).flat()])
    expect(/[✔◻◼]/u.test(s.text)).toBe(false)                    // 두 칸으로 그려져 숫자를 덮던 ✔ ◻ ◼ 는 없다
  const closed = LEFT(buildBand({ work, server: noSess, selfSid: 'self', columns: 160, expanded: true }), 160)
  const k = closed.findIndex(l => l.includes('할 일'))
  expect(closed[k - 1].trim()).toBe('')                                          // 학습 묶음과 빈 줄로 나뉜다
  expect(closed[k].trim()).toBe('할 일 완료 32 · 진행 2 · 남음 2  [펼치기]')
  expect(closed.join('\n')).not.toContain('스크래치')
  const openRows = buildBand({ work, server: noSess, selfSid: 'self', columns: 160, expanded: true, todosOpen: true })
  const open = LEFT(openRows, 160)
  const j = open.findIndex(l => l.includes('할 일'))
  expect(open[j]).toContain('[접기]')
  expect(open.slice(j + 1, j + 5).map(l => l.trim())).toEqual(['● 스크래치 스캔', '● A-0781 원인', '○ zip 여부 묻기', '○ cap 빈틈'])   // 정화
  expect(acts(openRows)).toContain('todos:toggle')
  for (const r of openRows) expect(lineWidth(r)).toBeLessThanOrEqual(156)
  // 진행·남은 것이 없으면 접힌 띠 칸은 없고, 할 일이 하나도 없으면 묶음도 없다
  const doneOnly = { ...idle, todos: { done: 3, doing: 0, open: 0, items: [] } }
  expect(txt(buildBand({ work: doneOnly, server: noSess, selfSid: 'self', columns: 120, expanded: false })[0])).toBe(' 작업  이상 없음')
  expect(LEFT(buildBand({ work: doneOnly, server: noSess, selfSid: 'self', columns: 160, expanded: true }), 160).join('\n')).not.toContain('[펼치기]')
  expect(LEFT(buildBand({ work: idle, server: noSess, selfSid: 'self', columns: 160, expanded: true }), 160).join('\n')).not.toContain('할 일')
})

test('고정 첫 줄(개정 26): 배지 + 버튼뿐이고, 좁아도 « 서버 » 배지가 쪼개져 둘째 줄로 밀리지 않는다', async () => {
  for (const columns of [40, 44, 50, 80, 160]) {
    const rows = buildBand({ work: idle, server, selfSid: 'self', columns, expanded: true })
    for (const r of rows) expect(lineWidth(r)).toBeLessThanOrEqual(columns - 4)
    const first = rows[0].filter(s => !s.button && !s.divider).map(s => s.text).join('').trim()
    expect(['작업', '작업   서버'].some(t => first.replace(/\s+/g, ' ') === t.replace(/\s+/g, ' '))).toBe(true)
    expect(rows.slice(1).some(r => r.some(s => s.tone === 'srvBadge' || s.tone === 'workBadge'))).toBe(false)   // 배지 조각이 둘째 줄 이하에 없다
  }
})

test('정화(개정 21): 폭 없는 글자와 아랍 글자 표지도 지운다', async () => {
  const name = 'a' + ch(0x200b, 0x200d, 0x2060, 0xfeff, 0x061c, 0x200f) + 'b'
  expect(sanitize({ ...server, sessions: [{ sid: 'b', name, status: 'idle' }] }, idle).server.sessions[0].name).toBe('ab')
})

test('빈 줄(개정 21): 서버 반은 GPU · 여유 메모리 · 디스크 묶음 사이마다 빈 줄 하나', async () => {
  const right = RIGHT(buildBand({ work: idle, server: { ...noSess, disks: [{ dev: 'sda', kind: 'SSD', mount: '/', total: 9 * GB, avail: 5 * GB }] }, selfSid: 'self', columns: 200, expanded: true }), 200)
  const gpu = right.findIndex(l => l.includes('GPU'))
  const mem = right.findIndex(l => l.includes('여유 메모리'))
  const disk = right.findIndex(l => l.includes('디스크'))
  expect(right[mem - 1].trim()).toBe('')
  expect(right[disk - 1].trim()).toBe('')
  expect(gpu).toBeLessThan(mem)
  expect(mem + 2).toBe(disk)
})

test('정화: 세션 job 은 8자리 16진만', async () => {
  const { server: sv } = sanitize({ sessions: [{ sid: 'a', name: 'n', status: 'idle', job: '0c7530cd' }, { sid: 'b', name: 'n', status: 'idle', job: '0c7530cd; rm' }, { sid: 'c', name: 'n', status: 'idle', job: 5 }] }, {})
  expect(sv.sessions.map(s => s.job)).toEqual(['0c7530cd', null, null])
})

test('펼친 세션 줄: 한 세션은 한 줄(긴 활동은 …로 자르고 잇지 않는다), 좁으면 상태 → 활동 열 순으로 빠지고 모든 줄이 한도 안', async () => {
  const long = { sid: 'b', name: '[PRJ] Manager', status: 'shell', job_state: 'working', job_detail: '아주 긴 현재 활동 설명 '.repeat(8) }
  for (const columns of [60, 70, 80, 100, 120, 160]) {
    const rows = buildBand({ work: idle, server: { ...noSess, sessions: [long] }, selfSid: 'self', columns, expanded: true })
    for (const r of rows) expect(lineWidth(r)).toBeLessThanOrEqual(columns - 4)
    const lines = LEFT(rows, columns), k = lines.findIndex(l => l.includes('● [P'))   // 60열은 이름 열도 줄어 «[K…»
    expect(k).toBeGreaterThan(0)
    expect((lines[k + 1] || '').includes('아주')).toBe(false)   // 둘째 줄로 잇지 않는다
    if (columns >= 80) {   // 개정 26: 왼쪽 반이 7칸 넓어져 활동 열이 생기는 경계가 100열에서 80열로 내려갔다
      expect(lines[k]).toContain('아주')                          // 활동 열이 있고(80열은 «아주 …» 로 잘린다)
      expect(lines[k].endsWith('…')).toBe(true)                   // 넘치면 …
    }
    if (columns >= 160) expect(lines[k]).toContain('아주 긴')     // 넓으면 활동 앞부분이 낱말째 보인다(qa 2026-10-23, 100·120열은 상태 열이 생겨 «아주 …»)
    if (columns >= 120) expect(lines[k]).toContain('작업 중')     // 상태 열은 이름이 다 들어갈 만큼 넓을 때만
    if (columns <= 70) expect(lines[k]).not.toContain('아주')    // 아주 좁으면 활동 열을 뺀다
  }
})

test('펼친 보기 높이: 판 줄은 70열에서 두 줄로 나뉘어 …가 없고, 체크포인트가 많아도 줄 수가 늘지 않으며 합친 줄 폭은 한도 안', async () => {
  const ck = Array.from({ length: 3 }, (_, i) => ({ epoch: i * 5 + 4, value: -0.2 - i / 100 }))
  const run = { ...RUN_A, metric: '', done: 17, watcher: true, ckpts: ck }
  // 개정 26: 들여쓰기 7칸이 빠져 80열 반 폭(36칸)에는 판 줄이 한 줄로 들어가므로, 갈라지는 경계가 70열(반 폭 31칸)로 내려갔다
  const rows = buildBand({ work: idle, server: { ...noSess, train: [run] }, selfSid: 'self', columns: 70, expanded: true })
  for (const r of rows) expect(lineWidth(r)).toBeLessThanOrEqual(66)
  const lines = LEFT(rows, 70)
  expect(lines[1]).toBe('학습 GPU3 x72-1t  17/60  와쳐')   // 판 줄은 반 폭(31칸)에서 갈라지고 last 는 둘째 줄에 이어진다
  expect(lines[2]).toBe('  last')   // 이어 쓰는 줄은 2칸 들여쓰기
  expect(lines.join('\n')).not.toMatch(/…|체크포인트/)
  // 한쪽만 두 줄이면 다른 쪽은 빈 줄: 오른쪽 반이 비어도 구분선은 모든 줄에 있다
  for (const row of rows) expect(row.some(s => s.text === ' │ ')).toBe(true)
  // 체크포인트 20개·지표가 있어도 줄 수는 같다(판 줄만 남는다)
  const huge = { ...run, metric: 'val_score', ckpts: Array.from({ length: 20 }, (_, i) => ({ epoch: i, value: -0.123456 })) }
  const hl = buildBand({ work: idle, server: { ...noSess, train: [huge] }, selfSid: 'self', columns: 70, expanded: true })
  expect(hl.length).toBe(rows.length)
  expect(LEFT(hl, 70)).toEqual(lines)
})

test('splitAt: 셀 폭으로 가르고 tone 을 유지하며 합치면 원문과 같다', async () => {
  const row = [{ text: 'ab', tone: 'ok' }, { text: '가나다', tone: 'hot' }, { text: 'xy', tone: 'dim' }]
  const [h, r] = splitAt(row, 5)
  expect(h).toEqual([{ text: 'ab', tone: 'ok' }, { text: '가', tone: 'hot' }])
  expect(lineWidth(h)).toBeLessThanOrEqual(5)
  expect(h.concat(r).map(s => s.text).join('')).toBe('ab가나다xy')
  expect(r[0].tone).toBe('hot')
  expect(splitAt(row, 99)).toEqual([row, []])
})

test('세션 정화: job_state 형식·detail 제어 문자와 길이', async () => {
  const s = (job_state, job_detail) => sanitize({ ...server, sessions: [{ sid: 'b', name: 'n', status: 'shell', job_state, job_detail }] }, idle).server.sessions[0]
  expect(s('working', 'ok')).toMatchObject({ job_state: 'working', job_detail: 'ok' })
  for (const bad of ['Working', 'a-b', 'x'.repeat(21), 5, null, undefined, '__proto__ ']) expect(s(bad, null).job_state).toBe(null)
  expect(s('working', 5).job_detail).toBe(null)
  expect(s('working', '').job_detail).toBe(null)
  const d = s('working', 'a' + BAD + 'b' + '가'.repeat(100)).job_detail
  expect(hasBad(d)).toBe(false)
  expect(d.startsWith('ab')).toBe(true)
  expect(cellWidth(d)).toBeLessThanOrEqual(120)
  // 알 수 없는 job_state(예: __proto__ 같은 상속 키)는 status 로 분류
  const odd = buildBand({ work: idle, server: { ...noSess, sessions: [{ sid: 'b', name: 'n', status: 'busy', job_state: '__proto__', job_detail: null }] }, selfSid: 'self', columns: 120, expanded: false })
  expect(txt(odd[0])).toContain('세션 ●1')
})

test('세션 칸 조회 실패: sessions 가 null 이면 작업 줄에 «세션 (조회 실패)»', async () => {
  const rows = buildBand({ work: idle, server: { ...server, sessions: null }, selfSid: 'self', columns: 120, expanded: false })
  expect(txt(rows[0])).toBe(' 작업  이상 없음 │ 세션 (조회 실패)')
})

// ---- 개정 14(2026-10-17): 펼친 보기 서버 반의 디스크 장치별 줄 ----
const DISKS = [
  { dev: 'sdd', kind: 'SSD', mount: '/mnt/ssd', total: 2000 * GB, avail: 500 * GB },
  { dev: 'sda2', kind: 'SSD', mount: '/', total: 900 * GB, avail: 40 * GB },
  { dev: 'sdb', kind: 'HDD', mount: '/mnt/hdd0', total: 2000 * GB, avail: 600 * GB },
  { dev: 'sdc', kind: 'HDD', mount: '/mnt/hdd1', total: 2000 * GB, avail: 1500 * GB }]
const withDisks = { ...noSess, disks: DISKS }
const devRows = (sv, columns: number) => buildBand({ work: idle, server: sv, selfSid: 'self', columns, expanded: true })

test('디스크 장치 줄: 메모리 줄 + 장치마다 한 줄(SSD → HDD 순), «디스크» 라벨은 첫 줄에만', async () => {
  const right = RIGHT(devRows(withDisks, 120), 120)
  const mem = right.findIndex(l => l.includes('여유 메모리 212/503G'))
  expect(mem).toBeGreaterThanOrEqual(0)
  expect(right[mem]).not.toContain('디스크')                            // 접힌 띠와 달리 메모리 줄에 디스크가 붙지 않는다
  const lines = right.filter(l => /SSD|HDD/.test(l))
  const want = ['디스크 SSD sdd /mnt/ssd 500/2000G', 'SSD sda2 / 40/900G', 'HDD sdb /mnt/hdd0 600/2000G', 'HDD sdc /mnt/hdd1 1500/2000G']
  expect(lines.length).toBe(4)
  want.forEach((w, i) => expect(lines[i].trim()).toBe(w))
  expect(right.join('\n').split('디스크').length - 1).toBe(1)           // 라벨 한 번
  const first = right.findIndex(l => l.includes('디스크 SSD'))
  expect(first).toBe(mem + 2)                                             // 메모리 줄과 디스크 줄 사이 빈 줄(개정 21)
  expect(right[mem + 1].trim()).toBe('')
  expect(right[first + 1].startsWith(' '.repeat(7))).toBe(true)         // 개정 26: 서버 반 들여쓰기 7칸이 없어져 «디스크 » 와 같은 폭 7칸만
  expect(right[first + 1].startsWith(' '.repeat(8))).toBe(false)
})

test('디스크 장치 줄: 종류는 라벨 톤, 수치 톤은 장치별 여유 비율(10% 미만 hot · 20% 미만 warn)', async () => {
  const sv = { ...noSess, disks: [
    { dev: 'sda2', kind: 'SSD', mount: '/', total: 100 * GB, avail: 5 * GB },
    { dev: 'sdb', kind: 'HDD', mount: '/b', total: 100 * GB, avail: 15 * GB },
    { dev: 'sdc', kind: 'HDD', mount: '/c', total: 100 * GB, avail: 50 * GB }] }
  const segs = devRows(sv, 200).flat()
  expect(segs.filter(s => s.text === 'SSD' || s.text === 'HDD').every(s => s.tone === 'label')).toBe(true)
  expect(segs.find(s => s.text === '5/100G')!.tone).toBe('hot')
  expect(segs.find(s => s.text === '15/100G')!.tone).toBe('warn')
  expect(segs.find(s => s.text === '50/100G')!.tone).toBe('base')
})

test('디스크 장치 줄: 좁은 80열에서도 모든 줄이 한도 안이고 긴 줄은 둘째 줄에 이어 쓴다', async () => {
  const rows = devRows(withDisks, 80)
  for (const r of rows) expect(lineWidth(r)).toBeLessThanOrEqual(76)
  const right = RIGHT(rows, 80).join('\n')
  for (const d of ['SSD sdd', 'SSD sda2', 'HDD sdb', 'HDD sdc']) expect(right).toContain(d)
  expect(right.split('디스크').length - 1).toBe(1)
})

test('디스크 목록 정화: 숫자 아님·Infinity·음수 항목만 버리고, 종류는 SSD·HDD 외 «?», 8장치 상한', async () => {
  const bad = [
    { dev: 'ok', kind: 'SSD', mount: '/ok', total: 10 * GB, avail: 5 * GB },
    { dev: 'inf', kind: 'SSD', mount: '/i', total: Infinity, avail: 1 },
    { dev: 'neg', kind: 'SSD', mount: '/n', total: 10 * GB, avail: -1 },
    { dev: 'str', kind: 'SSD', mount: '/s', total: '10', avail: 5 },
    { dev: '', kind: 'SSD', mount: '/e', total: 10 * GB, avail: 5 * GB },
    { dev: 'weird', kind: 'NVMe', mount: '/w' + BAD, total: 10 * GB, avail: 5 * GB }, null, 7, 'x']
  const got = sanitize({ ...server, disks: bad }, idle).server.disks
  expect(got!.map(d => d.dev)).toEqual(['ok', 'weird'])
  expect(got![1].kind).toBe('?')
  expect(hasBad(got![1].mount)).toBe(false)
  const many = Array.from({ length: 12 }, (_, i) => ({ dev: `sd${i}`, kind: 'HDD', mount: '/m', total: 10 * GB, avail: 5 * GB }))
  expect(sanitize({ ...server, disks: many }, idle).server.disks!.length).toBe(8)
})

test('disks 가 없거나 비거나 전부 비정상이면 종전처럼 루트 디스크 한 줄(호환)', async () => {
  const old = RIGHT(devRows(noSess, 120), 120).join('\n')
  expect(old).toContain('여유 메모리 212/503G · 디스크 121/931G')
  for (const disks of [undefined, null, [], [{ dev: 'x', kind: 'SSD', mount: '/', total: Infinity, avail: 1 }], 'sda']) {
    expect(RIGHT(devRows({ ...noSess, disks }, 120), 120).join('\n')).toBe(old)
  }
})

test('접힌 띠는 disks 가 있어도 루트 디스크만 보인다(개정 13 그대로)', async () => {
  const a = buildBand({ work: idle, server: noSess, selfSid: 'self', columns: 80, expanded: false }).map(txt)
  const b = buildBand({ work: idle, server: withDisks, selfSid: 'self', columns: 80, expanded: false }).map(txt)
  expect(b).toEqual(a)
  expect(b.join('\n')).not.toMatch(/SSD|HDD/)
})

// ---- 개정 15(2026-10-21): 좌우 경계 split · divider 표시 · view 의 band-divider Client ----
test('effectiveSplit: 양쪽 최소 24칸으로 자르고, 반 폭이 24 미만이거나 수가 아니면 0', async () => {
  // columns 120 → 반 폭 floor((120-4-3)/2)=56: 허용 범위는 -32 ~ +32
  expect(effectiveSplit(120, 0)).toBe(0)
  expect(effectiveSplit(120, 10)).toBe(10)
  expect(effectiveSplit(120, -10)).toBe(-10)
  expect(effectiveSplit(120, 32)).toBe(32)
  expect(effectiveSplit(120, 33)).toBe(32)
  expect(effectiveSplit(120, 999)).toBe(32)
  expect(effectiveSplit(120, -32)).toBe(-32)
  expect(effectiveSplit(120, -33)).toBe(-32)
  expect(effectiveSplit(120, -999)).toBe(-32)
  expect(effectiveSplit(120, 2.6)).toBe(3)   // 셀 수라 반올림
  // 반 폭 < 24 (columns 54 → 23) 인 좁은 터미널은 어떤 값이든 0
  for (const v of [-30, -1, 0, 1, 30]) expect(effectiveSplit(54, v)).toBe(0)
  expect(effectiveSplit(55, 5)).toBe(0)       // 반 폭 24: 범위가 0 한 점
  // 수가 아니면 0
  for (const bad of [NaN, Infinity, -Infinity, '5', null, undefined, {}]) expect(effectiveSplit(120, bad as never)).toBe(0)
})

test('split: 왼쪽 폭이 그만큼 바뀌고 오른쪽이 나머지를 받으며, 모든 줄 폭은 columns-4 이하이고 모든 펼친 줄에 divider 가 있다', async () => {
  const columns = 120, limit = columns - 4, half = Math.floor((limit - 3) / 2)
  const work = { codex: [{ model: 'gpt-6.1-sol', effort: 'xhigh' }], grok: [], train: { running: [], ended: [] } }
  for (const split of [0, 10, -10, 999, -999]) {
    const rows = buildBand({ work, server: { ...server, train: [SHORT_A] }, selfSid: 'self', columns, expanded: true, split })
    const left = half + effectiveSplit(columns, split)
    for (const r of rows) {
      expect(lineWidth(r)).toBeLessThanOrEqual(limit)
      const cells = r.filter(s => !s.button), k = cells.findIndex(s => s.divider)
      expect(k).toBeGreaterThan(0)
      expect(cells.filter(s => s.divider).length).toBe(1)
      expect(cells[k]).toEqual({ text: ' │ ', tone: 'sep', divider: true })   // 글자·tone 은 그대로
      expect(lineWidth(cells.slice(0, k))).toBe(left)                          // 왼쪽 폭 = 반 폭 + split
      expect(lineWidth(cells.slice(k + 1))).toBeLessThanOrEqual(2 * half - left)   // 오른쪽 = 2×반 폭 − 왼쪽
    }
  }
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b)
  const base = buildBand({ work, server, selfSid: 'self', columns, expanded: true })
  expect(same(buildBand({ work, server, selfSid: 'self', columns, expanded: true, split: 0 }), base)).toBe(true)   // split 0 = 인자 없음
  expect(same(buildBand({ work, server, selfSid: 'self', columns, expanded: true, split: 10 }), base)).toBe(false)
  // 접힌 띠에는 divider 가 없고 split 은 영향이 없다
  const collapsed = buildBand({ work, server, selfSid: 'self', columns, expanded: false, split: 10 })
  expect(collapsed.flat().some(s => s.divider)).toBe(false)
  expect(same(collapsed, buildBand({ work, server, selfSid: 'self', columns, expanded: false }))).toBe(true)
})

test('view toTree: el.Client 가 있으면 왼쪽 열 · band-divider Client · 오른쪽 열, 없으면 줄마다 ` │ ` 글자', async () => {
  const rows = buildBand({ work: idle, server, selfSid: 'self', columns: 140, expanded: true, split: 6 })   // 칩 버튼 4개(폭 50)를 두고도 « 서버 » 배지가 들어가는 폭
  const withClient = { ...el, Client: p => ({ t: 'Client', ...p }) }
  const tree = toTree(withClient, rows, 'dark', 6)
  expect(tree.flexDirection).toBe('row')
  expect(tree.children.map(c => c.key)).toEqual(['band-left', 'band-divider', 'band-right'])
  const [l, d, r] = tree.children
  expect(d.t).toBe('Client')
  expect(d.module).toMatch(/divider\.js$/)   // 시험 러너가 소스의 './divider.js' 를 플러그인 루트 기준 'hooks/band/divider.js' 로 바꿔 넘긴다
  expect(d.width).toBe(3)
  expect(d.height).toBe(rows.length)
  expect(d.props).toEqual({ rows: rows.length, offset: 6, fg: PALETTES.dark.sep, active: PALETTES.dark.btn, bg: PALETTES.dark.bg })
  expect(l.children.length).toBe(rows.length)
  expect(r.children.length).toBe(rows.length)
  const texts = (n: any) => { const out: string[] = []; walk(n, x => { if (x.t === 'Text') out.push(x.children.join('')) }); return out }
  expect(texts(l)).not.toContain(' │ ')   // 경계 글자는 Client 가 그린다
  expect(texts(r)).not.toContain(' │ ')
  expect(texts(l)[0]).toBe(' 작업 ')
  expect(texts(r)[0]).toBe(' 서버 ')
  const buttons: any[] = []
  walk(r.children[0], x => { if (x.t === 'Button') buttons.push(x) })   // 버튼은 오른쪽 열 첫 줄 끝
  expect(buttons.map(b => b.key)).toEqual(['band-mobile', 'band-mask', 'band-big', 'band-toggle'])   // 2026-11-03: 모바일 · 마스킹 · 크게 · 접기
  expect(buttons.map(b => b.label)).toEqual(['📱 모바일 off', '🔒 마스킹 on', '크게 ⇱', '접기 ▾'])   // 라벨은 칩 여백을 뗀 글자
  walk(l.children[0], x => expect(x.t).not.toBe('Button'))   // 왼쪽 첫 줄(작업 배지 줄)에는 버튼이 없다(세션 줄의 [숨김] 은 아래 줄)
  // Client 가 없는 화면은 종전처럼 한 열 Box 안에서 줄마다 ` │ ` 글자
  const plain = toTree(el, rows, 'dark', 6)
  expect(plain.flexDirection).toBe('column')
  expect(plain.children.length).toBe(rows.length)
  let clients = 0
  walk(plain, x => { if (x.t === 'Client') clients++ })
  expect(clients).toBe(0)
  for (const row of plain.children) expect(texts(row)).toContain(' │ ')
  // 접힌 띠(divider 없음)는 Client 가 있어도 Client 를 넣지 않는다
  const folded = toTree(withClient, buildBand({ work: idle, server, selfSid: 'self', columns: 120, expanded: false }), 'dark', 6)
  let foldedClients = 0
  walk(folded, x => { if (x.t === 'Client') foldedClients++ })
  expect(foldedClients).toBe(0)
})
