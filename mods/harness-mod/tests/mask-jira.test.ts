import { expect, mock, test } from 'claude-code/testing'
import { maskOutput, maskText } from '../hooks/band/mask.js'
import { BTN_RESERVE, DETAIL_BTN_RESERVE, JIRA_KEY, buildBand, cleanJira } from '../hooks/band/model.js'
import { lineWidth } from '../hooks/band/width.js'

// 개정 27(intent/2026-10-23-mods-jira-mermaid-mask-typo.md): 화면 가림 · 가림 버튼 배치 · AssistantMessage 훅(mermaid + 가림) · Jira 이슈 묶음.

// 가짜 비밀값은 조각을 실행 때 잇는다 — 커밋 게이트·공개 내보내기의 gitleaks 가 시험 자료에 걸리지 않게(바이트는 같다).
const FAKE_SK = 'sk-' + 'abcdefgh12345678'
const FAKE_JWT = 'eyJ' + 'hbGciOiJIUzI1NiJ9.' + 'eyJ' + 'zdWIiOiIxMjM0NTY3ODkwIn0.' + 'abcDEF123_-xyz'

// ---- maskText: 대상 ----
test('maskText: 이메일 · JWT · API 토큰 꼴 · 긴 Base64 를 표시로 바꾸고 개수를 센다', () => {
  const email = maskText('문의는 a.b+c@example.co.kr 로 주십시오')
  expect(email).toEqual({ text: '문의는 «이메일 가림» 로 주십시오', count: 1 })
  const jwt = maskText('Bearer ' + FAKE_JWT + ' 끝')
  expect(jwt).toEqual({ text: 'Bearer «JWT 가림» 끝', count: 1 })
  // 가짜 토큰은 접두와 꼬리를 나눠 실행 때 잇는다 — 커밋 비밀값 검사가 시험 자료에 걸리지 않게(바이트는 같다).
  const T = (head: string, tail: string) => head + tail
  for (const tok of [T('sk-', 'abcdefgh12345678'), T('sk-ant-', 'api03-abcdefghijkl'), T('ghp_', 'abcdefghij1234'), T('github_pat_', '11ABCDEFG0abcdef'), T('xoxb-', '1234-abcdefgh'),
    T('xoxa-', '1234-abcdefgh'), T('xoxp-', '1234-abcdefgh'), T('AKIA', 'IOSFODNN7EXAMPLE'), T('tvly-', 'dev-abcdefgh1')]) {
    expect(maskText(`키 ${tok} 입니다`)).toEqual({ text: '키 «토큰 가림» 입니다', count: 1 })
  }
  expect(maskText('b64 QWxhZGRpbjpvcGVuIHNlc2FtZVNlY3JldEtleTEyMzQ1Njc4OTA= ok')).toEqual({ text: 'b64 «Base64 가림» ok', count: 1 })
  expect(maskText('a@example.com 그리고 b@example.org').count).toBe(2)
})

test('maskText: 코드 블록 안도 가린다', () => {
  expect(maskText('```sh\nexport TOKEN=' + FAKE_SK + '\n```').text).toBe('```sh\nexport TOKEN=«토큰 가림»\n```')
})

// ---- maskText: 비대상 ----
test('maskText: 커밋 해시(16진수만) · 일반 영문 · URL · 경로 · 패키지 버전은 그대로 둔다', () => {
  const keep = [
    '커밋 0123456789abcdef0123456789abcdef01234567 입니다',
    'sha256 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',
    'ABCDEF0123456789ABCDEF0123456789ABCDEF01',
    'plain English text with ThisIsALongCamelCaseIdentifierWithoutDigits okay',
    'https://example.com/AbCdEfGhIjKlMnOpQrStUvWxYz0123456789AbCdEf/x',
    '/home/user/workspace/ClaudeCode123/AbcDefGhi/Jkl/Mno/Pqr1/Stu2/vwx',
    'react@18.2.0 와 @types/node',
    'disk-usage-report-generator 와 task-abcdefghijk',
    '짧은 eyJ 와 sk- 만',
  ]
  for (const t of keep) expect(maskText(t)).toEqual({ text: t, count: 0 })
  const s = '아무것도 없는 글'
  expect(maskText(s).text).toBe(s)
})

test('maskOutput: Bash stdout·stderr · Read 파일 내용 · 문자열을 가리고 바뀐 게 없으면 같은 객체를 돌려준다', () => {
  const out = { stdout: 'TOKEN=' + FAKE_SK, stderr: 'x@example.com', interrupted: false }
  expect(maskOutput(out)).toEqual({ stdout: 'TOKEN=«토큰 가림»', stderr: '«이메일 가림»', interrupted: false })
  expect(out.stdout).toBe('TOKEN=' + FAKE_SK)   // 원본 객체는 바꾸지 않는다
  expect(maskOutput({ file: { content: 'a@example.com', numLines: 1 } })).toEqual({ file: { content: '«이메일 가림»', numLines: 1 } })
  expect(maskOutput('a@example.com')).toBe('«이메일 가림»')
  const clean = { stdout: 'ok', stderr: '' }
  expect(maskOutput(clean)).toBe(clean)
  for (const odd of [null, undefined, 5, [1, 2], { stdout: 5 }]) expect(maskOutput(odd as never)).toBe(odd)
})

test('maskText: Atlassian · GitHub · GitLab · Google · HuggingFace 토큰 꼴과 URL-safe Base64 를 가린다', () => {
  const J = (head: string, tail: string) => head + tail   // 위와 같은 까닭으로 나눠 잇는다
  const toks = [J('ATATT', '3xFfGF0abcdefghijklmnopqrstuvwx=1A2B3C4D'), J('gho_', 'abcdefghij1234'), J('ghs_', 'abcdefghij1234'), J('ghu_', 'abcdefghij1234'), J('ghr_', 'abcdefghij1234'),
    J('glpat-', 'abcdefghij1234567890'), J('AIza', 'SyA1234567890abcdefghijklmnop_qrstu'), J('hf_', 'abcdefghijklmnopqrstuvwxyzABCDEF')]
  for (const tok of toks) expect(maskText(`키 ${tok} 입니다`)).toEqual({ text: '키 «토큰 가림» 입니다', count: 1 })
  expect(maskText('b64 QWxhZGRpbjpvcGVuIHNlc2FtZV-lY3JldEtleTEyMzQ1Njc4OT_A ok')).toEqual({ text: 'b64 «Base64 가림» ok', count: 1 })
  const keep = ['hf_short 와 glpat-x', 'my-long-kebab-case-name-with-only-lowercase-letters-and-words-here']
  for (const t of keep) expect(maskText(t)).toEqual({ text: t, count: 0 })
})

// 성능(검수 2026-10-23): 공백 없는 긴 글에서도 maskText 가 200ms 안에 끝나야 한다(mod 는 단일 스레드라 렌더 훅이 멈추면 전체가 멈춘다).
test('maskText 성능: 공백 없는 300KB Base64 · a×300000 · a@×100000 · 이메일 비슷한 줄 · eyJ 반복이 각각 200ms 안에 끝난다', () => {
  const ABC = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
  const b64 = Array.from({ length: 300000 }, (_, i) => ABC[(i * 2654435761 + (i >> 3)) % 64]).join('')
  const cases: Record<string, string> = {
    'base64 -w0 300KB': b64,
    'a×300000': 'a'.repeat(300000),
    'a@×100000': 'a@'.repeat(100000),
    '이메일 비슷한 줄': 'a.b'.repeat(40000) + '@' + 'x.'.repeat(40000),
    '점 이어진 로컬부': 'a.'.repeat(150000),
    'eyJ×100000': 'eyJ'.repeat(100000),
    'sk-×100000': 'sk-'.repeat(100000),
    '슬래시 조각': 'aA1' + '//'.repeat(100000),
    '공백 섞인 base64': ('QWxhZGRpbjpvcGVuIHNlc2FtZVNlY3JldEtleTEyMzQ1Njc4OTA ').repeat(5000),
  }
  for (const [name, text] of Object.entries(cases)) {
    const t0 = performance.now()
    const r = maskText(text)
    const ms = performance.now() - t0
    console.log(`PERF mask ${name} ${ms.toFixed(1)}ms`)
    expect(`${name} ${ms < 200}`).toBe(`${name} true`)
    expect(typeof r.text).toBe('string')
  }
})

test('maskText: 가림 대상 길이 상한(200KB) 을 넘으면 앞부분만 가리고 나머지는 원문 대신 생략 표시로 잘라 보인다(원문이 새지 않는다)', () => {
  const secret = 'sk-' + 'A1b2C3d4'.repeat(4)
  const r = maskText('x'.repeat(250000) + ' ' + secret)
  expect(r.text.length).toBeLessThan(200100)
  expect(r.text.endsWith('«(이하 생략: 가림 대상 초과)»')).toBe(true)
  expect(r.text.includes(secret)).toBe(false)
  expect(r.count).toBeGreaterThanOrEqual(1)
  expect(maskOutput({ stdout: 'y'.repeat(2500000) + ' ' + secret, stderr: '' })).toMatchObject({ stderr: '' })   // 예전 2MB 상한처럼 원문을 그대로 두지 않는다
  expect((maskOutput('y'.repeat(2500000) + ' ' + secret) as string).includes(secret)).toBe(false)
  // 긴 로컬부 이메일도 가린다(로컬부 길이 상한을 두지 않는다)
  expect(maskText(`${'a'.repeat(100)}@example.com`).text).toBe('«이메일 가림»')
})

// ---- 첫 줄 버튼 배치 ----
const SERVER = { gpus: [{ i: 0, util: 0, used: 14, total: 46068 }], mem: { total: 503 * 2 ** 30, avail: 212 * 2 ** 30 }, disk: { total: 879 * 2 ** 30, avail: 121 * 2 ** 30 }, sessions: [] }
const IDLE = { codex: [], grok: [], train: { running: [], ended: [] } }
const band = (columns: number, extra: object = {}) => buildBand({ work: IDLE, server: SERVER, selfSid: 'self', columns, expanded: false, ...extra })

test('버튼 배치(접힘): [가림] 이 [상세] 바로 왼쪽이고 사이에 여백 한 칸 이상, 오른쪽 끝은 [상세]', () => {
  const b = band(200)[0].filter(s => s.button)
  expect(b.map(s => s.key ?? 'gap')).toEqual(['band-mask', 'gap', 'band-toggle'])
  expect(b[0].text).toBe('가림 켬')
  expect(b[1].spacer && b[1].text.length >= 1).toBe(true)
  expect(b[2].text).toBe('상세 ▸')
  expect(lineWidth(b) + 1).toBe(BTN_RESERVE)
  expect(band(200, { maskOn: false })[0].find(s => s.key === 'band-mask').text).toBe('가림 끔')
})

test('버튼 배치(펼침): [크게] · [가림] · [접기] 순서, 사이 여백, 오른쪽 끝은 [접기]', () => {
  const b = band(200, { expanded: true })[0].filter(s => s.button)
  expect(b.map(s => s.key ?? 'gap')).toEqual(['band-big', 'gap', 'band-mask', 'gap', 'band-toggle'])
  expect(b[1].text.length).toBeGreaterThanOrEqual(1)
  expect(b[3].text.length).toBeGreaterThanOrEqual(1)
  expect(b[4].text).toBe('접기 ▾')
  expect(lineWidth(b) + 1).toBe(DETAIL_BTN_RESERVE)
  expect(band(200, { expanded: true, maskOn: false })[0].find(s => s.key === 'band-mask').text).toBe('가림 끔')
})

test('버튼 배치: 좁은 폭에서도 줄이 한도를 넘지 않고 [상세]/[접기] 는 항상 마지막에 남으며 남은 버튼 순서는 유지된다', () => {
  for (const expanded of [false, true]) {
    for (const columns of [200, 120, 80, 60, 50, 46, 44, 40, 36, 30]) {
      const rows = band(columns, { expanded })
      for (const r of rows) expect(lineWidth(r)).toBeLessThanOrEqual(columns - 4)
      const btns = rows[0].filter(s => s.button && !s.spacer)
      expect(btns[btns.length - 1].key).toBe('band-toggle')
      const keys = btns.map(s => s.key)
      const order = ['band-big', 'band-mask', 'band-toggle'].filter(k => keys.includes(k))
      expect(keys).toEqual(order)
      if (columns >= 80) expect(keys).toContain('band-mask')
    }
  }
})

// ---- Jira 줄 계산 ----
const ITEMS = [{ key: 'XYZ-1', status: '진행 중', summary: '첫 «이슈»', updated: '', url: '' }, { key: 'ABC-22', status: '해야 할 일', summary: '둘째 이슈' }]
const jiraLines = (jira: object, columns = 160) => buildBand({ work: IDLE, server: SERVER, selfSid: 'self', columns, expanded: true, jira })
  .map(r => r.filter(s => !s.button).map(s => s.text).join(''))

test('Jira 줄: 접힘은 머리 줄만, 펼침은 이슈마다 «KEY [상태] 제목» 과 버튼 둘, 키가 틀린 이슈는 거른다', () => {
  expect(jiraLines({ open: false, items: null }).some(l => l.includes('Jira') && l.includes('내 이슈'))).toBe(true)
  expect(jiraLines({ open: false, items: ITEMS }).some(l => l.includes('ABC-22'))).toBe(false)
  const rows = buildBand({ work: IDLE, server: SERVER, selfSid: 'self', columns: 160, expanded: true,
    jira: { open: true, items: [...ITEMS, { key: 'bad-3', summary: 'x' }, { key: 'XYZ-9; rm', summary: 'x' }, { key: 'xyz-4', summary: 'x' }] } })
  const acts = rows.flat().filter(s => s.act && s.key && s.key.startsWith('band-jira-')).map(s => s.key)
  expect(acts).toEqual(['band-jira-work-XYZ-1', 'band-jira-draft-XYZ-1', 'band-jira-work-ABC-22', 'band-jira-draft-ABC-22'])
  const lines = jiraLines({ open: true, items: ITEMS })
  expect(lines.some(l => l.includes('Jira') && l.includes('내 이슈 2'))).toBe(true)
  expect(lines.some(l => /XYZ-1 \[진행 중\] 첫 이슈/.test(l))).toBe(true)   // 제목의 «» 는 지운다
  expect(lines.some(l => /ABC-22 \[해야 할 일\] 둘째 이슈/.test(l))).toBe(true)
  const headBtn = rows.flat().find(s => s.act === 'jira')
  expect(headBtn.text).toBe('[접기]')
  for (const columns of [160, 80, 60, 44]) for (const r of buildBand({ work: IDLE, server: SERVER, selfSid: 'self', columns, expanded: true, jira: { open: true, items: ITEMS } })) {
    expect(lineWidth(r)).toBeLessThanOrEqual(columns - 4)
  }
})

test('Jira 줄: 조회 실패는 «Jira 조회 실패: …» 한 줄, 이슈가 없으면 안내, 불러오는 중 표시', () => {
  const err = jiraLines({ open: true, items: null, error: '인증 실패\n(401)' })
  expect(err.filter(l => l.includes('Jira 조회 실패: 인증 실패 (401)') || l.includes('Jira 조회 실패: 인증 실패')).length).toBe(1)
  expect(jiraLines({ open: true, items: [] }).some(l => l.includes('배정된 미완료 이슈가 없습니다'))).toBe(true)
  expect(jiraLines({ open: true, items: null, loading: true }).some(l => l.includes('불러오는 중'))).toBe(true)
  expect(cleanJira(null)).toBe(null)
  expect(JIRA_KEY.test('XYZ-367')).toBe(true)
  expect(JIRA_KEY.test('xyz-367')).toBe(false)
})

// ---- 렌더·눌림·명령 (엔진 검증) ----
const SID = '0c7530cd-4cc9-47a1-9df0-ab9103f6e70d'
const SITE = {
  plugin: 'harness-mod',
  component: 'AbovePrompt',
  requestId: 'band',
  viewport: { columns: 200, rows: 40 },
  props: { hasSurvey: false, isWorking: false, maxRows: 30, bodyColumns: 200, scroll: { offset: 0, bodyRows: 29 }, view: {} },
} as const
const MSG = (text: string, extra: object = {}) => ({ plugin: 'harness-mod', component: 'AssistantMessage', requestId: 'msg', surface: 'terminal', viewport: { columns: 80, rows: 40 }, props: { text, isFirstOfReply: true }, ...extra }) as never
const RESULT = (output: unknown) => ({ plugin: 'harness-mod', component: 'ToolResult', requestId: 'res', surface: 'terminal', viewport: { columns: 80, rows: 40 }, props: { tool_use_id: 't1', tool: 'Bash', output, isErrored: false } }) as never

type Opts = { kv?: Map<string, unknown>, jira?: (argv: string[]) => { exitCode: number, stdout: string, stderr: string } | Error, ran?: any[], fills?: any[], registered?: any[], seen?: string[], outputs?: unknown[] }
function stubs(on, opts: Opts = {}) {
  const clock = mock.clock(on, { now: Date.now() })
  // 시험이 저장값을 읽을 수 있게 mock.store 대신 Map 으로 $.store 를 답한다(opts.kv 로 세션을 다시 띄워도 이어진다).
  const kv = opts.kv ?? new Map()
  on('store.get', (_$, e) => ({ value: kv.get(e.key) }))
  on('store.set', (_$, e) => { kv.set(e.key, e.value); return { value: undefined } })
  on('session.start', () => ({ cwd: '/work' }))
  on('command.register', (_$, e) => { opts.registered?.push(e); return { value: undefined } })
  on('session.surfaces', () => ({ value: ['terminal'] }))
  on('env.get', ($, e) => ({ value: (e.name === 'HOME' || e.key === 'HOME') ? '/home/user' : undefined }))
  on('session.id', () => ({ value: SID }))
  on('session.cwd', () => ({ value: '/work' }))
  on('process.run', ($, e) => {
    opts.ran?.push({ argv: e.argv.map(String), timeoutMs: e.timeoutMs ?? e.init?.timeoutMs })
    if (e.argv.some(a => String(a).endsWith('jira_comment.py'))) {
      const r = (opts.jira ?? (() => ({ exitCode: 0, stdout: '[]', stderr: '' })))(e.argv.map(String))
      if (r instanceof Error) throw r
      return { value: r }
    }
    return { value: { exitCode: 0, stdout: e.argv.some(a => String(a).endsWith('band_work_collect.py')) ? JSON.stringify(IDLE) : '', stderr: '' } }
  })
  on('fs.read', ($, e) => ({ value: e.path.endsWith('server.json') ? JSON.stringify({ ts: Date.now() / 1000, ...SERVER }) : '' }))
  on('prompt.fill', (_$, e) => { opts.fills?.push({ text: e.text, mode: e.mode }); return { isFilled: true } })
  on('ui.render', (_$, e) => {
    if (e.component === 'AssistantMessage') { opts.seen?.push(e.props.text); return { type: 'Text', props: {}, children: [e.props.text] } }
    if (e.component === 'ToolResult') { opts.outputs?.push(e.props.output); return { type: 'Text', props: {}, children: ['result'] } }
    return { type: 'Text', props: {}, children: ['drawn by Claude Code'] }
  })
  return clock
}
const settle = async (clock) => { for (let i = 0; i < 20; i++) { await clock.settle(); await new Promise(r => setTimeout(r, 1)) } }
const start = async ($, clock) => { await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' }); await settle(clock) }
const label = async (ui, key: string) => (await ui.find({ key })).props.label

test('가림 버튼: 접힘·펼침 둘 다 같은 key, 누르면 켬↔끔이 뒤집히고 $.store 에 남는다', async ($, on) => {
  const kv = new Map<string, unknown>()
  const clock = stubs(on, { kv })
  await start($, clock)
  const ui = await $.ui.mount({ ...SITE, surface: 'terminal' })
  expect(await label(ui, 'band-mask')).toBe('가림 켬')
  await ui.press({ key: 'band-mask' })
  await settle(clock)
  expect(await label(ui, 'band-mask')).toBe('가림 끔')
  expect(kv.get('band-mask')).toBe(false)
  if ((await label(ui, 'band-toggle')) === '상세 ▸') await ui.press({ key: 'band-toggle' })   // 펼침에도 같은 버튼
  await settle(clock)
  expect(await label(ui, 'band-toggle')).toBe('접기 ▾')
  expect(await label(ui, 'band-mask')).toBe('가림 끔')
  await ui.press({ key: 'band-mask' })
  await settle(clock)
  expect(await label(ui, 'band-mask')).toBe('가림 켬')
  expect(kv.get('band-mask')).toBe(true)
  await ui.press({ key: 'band-toggle' })
  await ui.unmount()
})

test('가림 버튼: 저장값이 끔이면 세션을 띄울 때 읽어 끔으로 시작한다(다시 띄워도 유지)', async ($, on) => {
  const clock = stubs(on, { kv: new Map<string, unknown>([['band-mask', false]]) })
  await start($, clock)
  const ui = await $.ui.mount({ ...SITE, surface: 'terminal' })
  expect(await label(ui, 'band-mask')).toBe('가림 끔')
  await ui.press({ key: 'band-mask' })                         // 정리: 켬으로
  await settle(clock)
  await ui.unmount()
})

test('AssistantMessage: mermaid 블록이 도해로 바뀌고 가림이 켜져 있으면 비밀이 가려지며, 끄면 원문 그대로 · 바뀐 게 없으면 그대로', async ($, on) => {
  const seen: string[] = []
  const clock = stubs(on, { seen })
  await start($, clock)
  const band = await $.ui.mount({ ...SITE, surface: 'terminal' })
  if ((await label(band, 'band-mask')) === '가림 끔') await band.press({ key: 'band-mask' })
  await settle(clock)
  const text = '메일 a@example.com 과 토큰 sk-abcdefgh12345678\n```mermaid\nflowchart TD\n  A --> B\n```\n끝'
  const m = await $.ui.mount(MSG(text))
  const last = () => seen[seen.length - 1]
  expect(last()).toContain('«이메일 가림»')
  expect(last()).toContain('«토큰 가림»')
  expect(last()).not.toContain('sk-abcdefgh12345678')
  expect(last()).toContain('```text')                                  // mermaid → 도해 펜스
  expect(last()).toContain('┌───┐')
  expect(last()).not.toContain('flowchart TD')
  expect(await m.find({ type: 'Text', text: /«이메일 가림»/ })).toBeDefined()
  await band.press({ key: 'band-mask' })                               // 끔: 이미 그려진 응답도 다시 그려져 원문이 보인다
  await settle(clock)
  expect(last()).toContain('a@example.com')
  expect(last()).toContain('sk-abcdefgh12345678')
  expect(last()).toContain('┌───┐')                                    // 도해 변환은 가림과 무관하게 남는다
  await m.unmount()
  seen.length = 0
  const plain = await $.ui.mount(MSG('그냥 글입니다. 바꿀 것이 없습니다.'))
  expect(last()).toBe('그냥 글입니다. 바꿀 것이 없습니다.')
  const broken = await $.ui.mount(MSG('```mermaid\npie title x\n"a": 1\n```', { requestId: 'm3' }))      // 못 읽는 문법은 원문 그대로
  expect(last()).toBe('```mermaid\npie title x\n"a": 1\n```')
  await plain.unmount()
  await broken.unmount()
  await band.press({ key: 'band-mask' })                               // 정리: 켬으로
  await settle(clock)
  await band.unmount()
})

test('ToolResult: 가림이 켜져 있으면 Bash stdout·stderr 와 파일 내용의 비밀이 가려지고, 구조는 그대로이며 끄면 원문', async ($, on) => {
  const outputs: unknown[] = []
  const clock = stubs(on, { outputs })
  await start($, clock)
  const band = await $.ui.mount({ ...SITE, surface: 'terminal' })
  if ((await label(band, 'band-mask')) === '가림 끔') await band.press({ key: 'band-mask' })
  await settle(clock)
  const r = await $.ui.mount(RESULT({ stdout: 'TOKEN=' + FAKE_SK, stderr: '', interrupted: false }))
  expect(outputs[outputs.length - 1]).toEqual({ stdout: 'TOKEN=«토큰 가림»', stderr: '', interrupted: false })
  await band.press({ key: 'band-mask' })
  await settle(clock)
  expect(outputs[outputs.length - 1]).toEqual({ stdout: 'TOKEN=' + FAKE_SK, stderr: '', interrupted: false })
  await r.unmount()
  await band.press({ key: 'band-mask' })
  await settle(clock)
  await band.unmount()
})

test('/jira: 명령이 등록되고, 실행하면 조회(읽기 전용 mine --json)해 이슈 줄과 버튼이 보이며 키가 틀린 이슈는 거른다', async ($, on) => {
  const ran: any[] = [], registered: any[] = []
  const kv = new Map<string, unknown>()
  const list = [{ key: 'XYZ-1', summary: '첫 «이슈»', status: '진행 중', updated: 'x', url: 'u' }, { key: 'bad-2', summary: 'x', status: 's' }, { key: 'ABC-22', summary: '둘째', status: '대기' }]
  const clock = stubs(on, { kv, ran, registered, jira: () => ({ exitCode: 0, stdout: JSON.stringify(list), stderr: '' }) })
  await start($, clock)
  expect(registered.some(r => r.name === 'jira' && r.description === '내 Jira 이슈 묶음 펼치기·접기')).toBe(true)
  const ui = await $.ui.mount({ ...SITE, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /XYZ-1/ })).toBeUndefined()
  await $.command.run({ command: 'jira' })
  await settle(clock)
  const calls = ran.filter(c => c.argv.some(a => a.endsWith('jira_comment.py')))
  expect(calls.length).toBe(1)
  expect(calls[0].argv).toEqual(['python3', '/home/user/.claude/scripts/jira_comment.py', 'mine', '--json', '--max', '8'])
  expect(calls[0].timeoutMs).toBe(20000)
  expect(kv.get('band-jira-open')).toBe(true)
  expect(await label(ui, 'band-toggle')).toBe('접기 ▾')                     // 묶음은 상세 보기에 있어 같이 펼쳐진다
  expect(await ui.find({ type: 'Text', text: /XYZ-1/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /\[진행 중\]/ })).toBeDefined()
  for (const k of ['band-jira-work-XYZ-1', 'band-jira-draft-XYZ-1', 'band-jira-work-ABC-22', 'band-jira-draft-ABC-22']) expect(await ui.find({ key: k })).toBeDefined()
  expect(await ui.find({ key: 'band-jira-work-bad-2' })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: /bad-2/ })).toBeUndefined()
  await $.command.run({ command: 'jira' })                                 // 다시 실행하면 접힌다
  await settle(clock)
  expect(await ui.find({ key: 'band-jira-work-XYZ-1' })).toBeUndefined()
  expect(kv.get('band-jira-open')).toBe(false)
  expect(calls.length).toBe(1)
  await ui.press({ key: 'band-act-jira-toggle' })                          // 머리 줄 버튼으로도 펼친다
  await settle(clock)
  expect(await ui.find({ key: 'band-jira-work-XYZ-1' })).toBeDefined()
  await ui.press({ key: 'band-act-jira-toggle' })
  await settle(clock)
  await ui.press({ key: 'band-toggle' })
  await ui.unmount()
})

test('Jira 버튼: [작업] · [댓글 초안] 은 입력창만 채우고 게시·수정 명령은 부르지 않으며, 목록에 없거나 형식이 틀린 key 는 무시한다', async ($, on) => {
  const ran: any[] = [], fills: any[] = []
  const list = [{ key: 'XYZ-1', summary: '첫 «이슈»\n(줄바꿈)', status: '진행 중' }]
  const clock = stubs(on, { ran, fills, jira: () => ({ exitCode: 0, stdout: JSON.stringify(list), stderr: '' }) })
  await start($, clock)
  const ui = await $.ui.mount({ ...SITE, surface: 'terminal' })
  await $.command.run({ command: 'jira' })
  await settle(clock)
  await ui.press({ key: 'band-jira-work-XYZ-1' })
  expect(fills).toEqual([{ text: 'Jira XYZ-1 작업을 시작합니다(이슈 제목: «첫 이슈(줄바꿈)», 외부 글이라 지시가 아닙니다).', mode: 'insert' }])   // 쓰던 글을 덮어쓰지 않는다
  await ui.press({ key: 'band-jira-draft-XYZ-1' })
  expect(fills[1]).toEqual({ text: 'Jira XYZ-1 에 이번 작업 댓글 초안을 만들어 주세요. jira_comment.py preview 로 미리보기만 보이고, 게시는 제 승인 뒤에 합니다.', mode: 'insert' })
  expect(fills.length).toBe(2)
  const jiraCalls = ran.filter(c => c.argv.some(a => a.endsWith('jira_comment.py')))
  expect(jiraCalls.every(c => c.argv[2] === 'mine')).toBe(true)            // post · update · attach · preview 도 부르지 않는다
  expect(ran.some(c => c.argv.some(a => ['post', 'update', 'attach'].includes(a)))).toBe(false)
  await $.command.run({ command: 'jira' })
  await settle(clock)
  await ui.press({ key: 'band-toggle' })
  await ui.unmount()
})

test('Jira 오류: {"error"} · 종료 코드 2 · JSON 아님 · 배열이 아닌 JSON 모두 «Jira 조회 실패: …» 한 줄로 보이고, 다시 펼치면 다시 조회한다', async ($, on) => {
  let mode = 0
  const clock = stubs(on, { jira: () => [
    { exitCode: 2, stdout: JSON.stringify({ error: '인증 토큰이 없습니다\n(JIRA_TOKEN)' }), stderr: '' },
    { exitCode: 1, stdout: '이상한 글', stderr: 'Traceback boom' },
    { exitCode: 0, stdout: 'null', stderr: '' },
    { exitCode: 0, stdout: JSON.stringify([{ key: 'XYZ-5', summary: '복구', status: '진행 중' }]), stderr: '' },
  ][mode++] })
  await start($, clock)
  const ui = await $.ui.mount({ ...SITE, surface: 'terminal' })
  const errLine = async (re: RegExp) => { await settle(clock); return await ui.find({ type: 'Text', text: re }) }
  await $.command.run({ command: 'jira' })
  expect(await errLine(/Jira 조회 실패: 인증 토큰이 없습니다 \(JIRA_TOKEN\)/)).toBeDefined()
  await $.command.run({ command: 'jira' })
  await $.command.run({ command: 'jira' })
  expect(await errLine(/Jira 조회 실패: Traceback boom/)).toBeDefined()
  await $.command.run({ command: 'jira' })
  await $.command.run({ command: 'jira' })
  expect(await errLine(/Jira 조회 실패: 응답을 읽지 못했습니다\(종료 코드 0\)/)).toBeDefined()
  await $.command.run({ command: 'jira' })
  await $.command.run({ command: 'jira' })
  await settle(clock)
  expect(await ui.find({ type: 'Text', text: /XYZ-5/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /Jira 조회 실패/ })).toBeUndefined()
  await $.command.run({ command: 'jira' })
  await settle(clock)
  await ui.press({ key: 'band-toggle' })
  await ui.unmount()
})

test('Jira: 펼친 동안 5분이 지나면 다시 조회하고, 접으면 조회하지 않는다', async ($, on) => {
  const ran: any[] = []
  const clock = stubs(on, { ran, jira: () => ({ exitCode: 0, stdout: '[]', stderr: '' }) })
  await start($, clock)
  const ui = await $.ui.mount({ ...SITE, surface: 'terminal' })
  const count = () => ran.filter(c => c.argv.some(a => a.endsWith('jira_comment.py'))).length
  await $.command.run({ command: 'jira' })
  await settle(clock)
  expect(count()).toBe(1)
  await clock.advance(120000)                                              // 2분: 아직 다시 부르지 않는다
  await settle(clock)
  expect(count()).toBe(1)
  await clock.advance(200000)                                              // 합계 5분 20초: 펼친 채라 한 번 더
  await settle(clock)
  expect(count()).toBe(2)
  await $.command.run({ command: 'jira' })                                 // 접는다
  await settle(clock)
  await clock.advance(700000)
  await settle(clock)
  expect(count()).toBe(2)
  await ui.press({ key: 'band-toggle' })
  await ui.unmount()
})
