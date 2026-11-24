// 띠 데이터 → 줄(세그먼트 배열). 순수 함수만 둔다(시험: tests/band.test.ts).
// 세그먼트 = { text, tone }. tone: label base run runBold ok ask warn hot no noBadge workBadge srvBadge sep dim self btn (view.js 가 팔레트 색으로 바꾼다).
// 규칙의 정본: intent/2026-10-15-harness-mods.md 개정 5·6-3·7, 시안 .scratch/0a1b2c3d/band_design/design.md 최종본.
// REF: knowledge/harness/code-history/mods__harness-mod__hooks__band__model.js.md
import { cellWidth, clip, lineWidth, splitAt } from './width.js'

const GB = 2 ** 30
// WHY: 켬/끔 버튼은 글자가 바뀌어도 폭이 같도록 «on» 은 뒤 여백 2, «off» 는 1을 둔다.
// 폭은 칩 여백을 포함한다: 📰 칩 7/8 · 📱 칩 14/15 · 🔒 칩 14/15 · «상세 ▸» 칩 8 (이모지 2칸, 한글 2칸).
export const NEWS_RESERVE = 9      // WHY: «📰 on»(칩 7)+2 / «📰 off»(칩 8)+1
export const MOBILE_RESERVE = 16   // WHY: «📱 모바일 on»(칩 14)+2 / «📱 모바일 off»(칩 15)+1
export const MASK_RESERVE = 16     // WHY: «🔒 마스킹 on»(칩 14)+2 / «🔒 마스킹 off»(칩 15)+1
export const TOGGLE_RESERVE = 9    // WHY: «상세 ▸»(칩 8) + 앞 간격 1. 가장 좁은 폭에서도 남는 최소 예약
export const BTN_RESERVE = NEWS_RESERVE + MOBILE_RESERVE + MASK_RESERVE + TOGGLE_RESERVE
export const DETAIL_BTN_RESERVE = MOBILE_RESERVE + MASK_RESERVE + 9 + TOGGLE_RESERVE // WHY: 펼친 보기 첫 줄 오른쪽 전체(뉴스 제외): 모바일 · 마스킹 · «크게 ⇱»(칩 8)+1 · «접기 ▾»(8) + 앞 간격 1. 오른쪽 반이 모자라면 detailButtons 가 줄인다
export const MIN_RESERVE = TOGGLE_RESERVE
const MIN_WORK = 14
const COLLAPSED_TIERS = [[true, true, true], [true, true, false], [true, false, false], [false, false, false]]
const tierReserve = ([n, m, k]) => TOGGLE_RESERVE + (n ? NEWS_RESERVE : 0) + (m ? MOBILE_RESERVE : 0) + (k ? MASK_RESERVE : 0)
const MAX_CELLS = 40
const MAX_DETAIL = 120

// WHY: 캐시·수집기 값은 신뢰하지 않는다(검수 security 1). 이 아래의 계산은 정화된 값만 받는다.
// NEVER: 지울 글자를 소스에 직접 넣지 않는다(코드 값으로 판정한다).
// NEVER: 수집기 band_work_collect.py 의 _STRIP_RANGES 와 따로 바꾸지 않는다(같은 집합이다, STRIP_RANGES 를 내보내 시험이 대조한다).
export const STRIP_RANGES = [[0x00, 0x1f], [0x7f, 0x9f], [0x2028, 0x202e], [0x2066, 0x2069], [0x200b, 0x200f], [0x2060, 0x2064], [0xfeff, 0xfeff], [0x061c, 0x061c],
  [0x00ad, 0x00ad], [0x206a, 0x206f], [0xfe00, 0xfe0f], [0xe0000, 0xe007f], [0x3164, 0x3164]]
const isStripped = c => STRIP_RANGES.some(([a, b]) => c >= a && c <= b)
const num = v => typeof v === 'number' && Number.isFinite(v)
const isObj = v => v !== null && typeof v === 'object'

function cut(s, max = MAX_CELLS) {
  let out = '', w = 0
  for (const ch of s) {
    if (isStripped(ch.codePointAt(0))) continue
    const cw = cellWidth(ch)
    if (w + cw > max) break
    out += ch
    w += cw
  }
  return out
}
const str = v => (typeof v === 'string' ? cut(v) : '')
const strOrNull = v => (typeof v === 'string' ? cut(v) : null)

function cleanGpus(list) {
  if (!Array.isArray(list)) return null
  const out = []
  for (const g of list) {
    if (!isObj(g) || ![g.i, g.util, g.used, g.total].every(num) || g.total <= 0) return null
    out.push({ i: g.i, util: g.util, used: g.used, total: g.total })
  }
  return out.length ? out : null
}

const cleanFree = f => (isObj(f) && num(f.total) && f.total > 0 && num(f.avail) ? { total: f.total, avail: f.avail } : null)

const DISK_KINDS = new Set(['SSD', 'HDD', '?'])
function cleanDisks(list) {
  if (!Array.isArray(list)) return null
  const out = []
  for (const d of list.slice(0, 8)) {
    if (!isObj(d) || !num(d.total) || d.total <= 0 || !num(d.avail) || d.avail < 0) continue
    const dev = str(d.dev)
    if (!dev) continue
    out.push({ dev, kind: DISK_KINDS.has(d.kind) ? d.kind : '?', mount: str(d.mount), total: d.total, avail: d.avail })
  }
  return out.length ? out : null
}

const JOB_STATE_OK = /^[a-z_]{1,20}$/
const JOB_OK = /^[0-9a-f]{8}$/   // WHY: «제거» 버튼이 `claude rm <잡 id>` 에 넘기는 값이라 8자리 16진만(개정 20)
const cleanSessions = list => (Array.isArray(list)
  ? list.filter(isObj).map(s => ({ sid: str(s.sid), name: str(s.name), status: str(s.status),
    job: typeof s.job === 'string' && JOB_OK.test(s.job) ? s.job : null,
    job_state: typeof s.job_state === 'string' && JOB_STATE_OK.test(s.job_state) ? s.job_state : null,
    job_detail: typeof s.job_detail === 'string' ? cut(s.job_detail, MAX_DETAIL) || null : null }))
  : null)

const cleanModels = list => (Array.isArray(list)
  ? list.filter(isObj).map(m => ({ model: strOrNull(m.model), effort: strOrNull(m.effort) }))
  : null)

function cleanTrain(t) {
  if (!isObj(t) || !Array.isArray(t.running) || !Array.isArray(t.ended)) return null
  const names = a => a.filter(x => typeof x === 'string').map(str)
  return { running: names(t.running), ended: names(t.ended) }
}

const int = v => (num(v) && Number.isInteger(v) && v >= 0 ? v : null)

function cleanTrainRuns(list) {
  if (!Array.isArray(list)) return null
  return list.filter(isObj).slice(0, 16).map(r => ({
    gpu: int(r.gpu), name: typeof r.name === 'string' ? cut(r.name, 60) : '', max_epochs: int(r.max_epochs), done: int(r.done), metric: str(r.metric),
    ckpts: (Array.isArray(r.ckpts) ? r.ckpts : []).filter(c => isObj(c) && int(c.epoch) !== null)
      .map(c => ({ epoch: c.epoch, value: num(c.value) ? c.value : null })).sort((a, b) => a.epoch - b.epoch).slice(-20),
    last: r.last === true,
    watcher: r.watcher === true ? true : r.watcher === false ? false : null,
  }))
}

const TODO_STATES = new Set(['doing', 'open'])
function cleanTodos(t) {
  if (!isObj(t)) return null
  const n = v => int(v) ?? 0
  const items = (Array.isArray(t.items) ? t.items : []).filter(x => isObj(x) && TODO_STATES.has(x.state) && typeof x.subject === 'string')
    .slice(0, 12).map(x => ({ state: x.state, subject: cut(x.subject, 60) }))
  return { done: n(t.done), doing: n(t.doing), open: n(t.open), items }
}

export function sanitize(server, work) {
  const sv = isObj(server) ? server : {}
  const wk = isObj(work) ? work : {}
  return {
    server: { gpus: cleanGpus(sv.gpus), mem: cleanFree(sv.mem), disk: cleanFree(sv.disk), disks: cleanDisks(sv.disks), sessions: cleanSessions(sv.sessions), train: cleanTrainRuns(sv.train) },
    work: { codex: cleanModels(wk.codex), grok: cleanModels(wk.grok), train: cleanTrain(wk.train), blocks: num(wk.blocks) ? wk.blocks : null, todos: cleanTodos(wk.todos) },
  }
}

const S = (text, tone = 'base') => ({ text, tone })
const SEP = () => S(' │ ', 'sep')
const TWO = () => S('  ')
const FAIL = () => S('(조회 실패)', 'dim')

const fmtG = bytes => Math.round(bytes / GB) + 'G'
const mibG = m => Math.round(m / 1024)
const fmtMiB = m => mibG(m) + 'G'

function joinSegs(groups, sep) {
  const out = []
  groups.forEach((g, i) => { if (i) out.push(sep()); out.push(...g) })
  return out
}

function fit(build, limit, maxLevel) {
  let segs
  for (let l = 0; l <= maxLevel; l++) {
    segs = build(l)
    if (lineWidth(segs) <= limit) return segs
  }
  return segs
}

const isIdleGpu = g => g.util < 5 && g.used < 2048
const gpuTone = g => { const r = g.used / g.total; return r >= 0.9 ? 'hot' : r >= 0.75 ? 'warn' : 'base' }
const freeTone = f => { const r = f.avail / f.total; return r < 0.1 ? 'hot' : r < 0.2 ? 'warn' : 'base' }

function gpuItem(g, level) {
  const t = gpuTone(g)
  if (level >= 8) return [S(String(g.i), t), S(' '), S(`${g.util}%`, t)]
  const mem = level >= 3 ? fmtMiB(g.used) : `${mibG(g.used)}/${fmtMiB(g.total)}`
  return [S(String(g.i)), S(' '), S(`${g.util}%`), S(' '), S(mem, t)]
}

function gpuCell(gpus, level) {
  const head = [S('GPU', 'label'), S(' ')]
  if (!gpus) return [...head, FAIL()]
  const sorted = [...gpus].sort((a, b) => a.i - b.i)
  const idle = sorted.filter(isIdleGpu)
  if (level >= 12) {
    const tones = sorted.filter(g => !isIdleGpu(g)).map(gpuTone)
    const t = tones.includes('hot') ? 'hot' : tones.includes('warn') ? 'warn' : 'base'
    const parts = []
    if (tones.length) parts.push(S(`사용${tones.length}`, t))
    if (idle.length) parts.push(S(`대기${idle.length}`, 'dim'))
    return [...head, ...joinSegs(parts.map(p => [p]), () => S(' '))]
  }
  const groups = []
  if (idle.length) groups.push([S(level >= 5 ? `대기${idle.length}` : idle.map(g => g.i).join('·') + ' 대기', 'dim')])
  for (const g of sorted.filter(g => !isIdleGpu(g))) groups.push(gpuItem(g, level))
  return [...head, ...joinSegs(groups, TWO)]
}

const own = (o, k) => Object.prototype.hasOwnProperty.call(o, k)
// WHY: blocked 는 2026-10-16 실측 값으로, 잡이 사용자 답을 기다리는 상태다(needs_input 과 같게 본다).
const JOB_KIND = { working: 'work', needs_input: 'ask', blocked: 'ask', done: 'idle', idle: 'idle', failed: 'fail' }
const STATUS_KIND = { busy: 'work', idle: 'idle' }
const JOB_LABEL = { working: '작업 중', needs_input: '입력 대기', blocked: '입력 대기', done: '끝남', idle: '쉼', failed: '실패' }
const STATUS_LABEL = { busy: '작업 중', idle: '쉼', shell: '셸 실행', waiting: '대기' }
const KIND_VIEW = { work: ['●', 'run'], ask: ['◐', 'warn'], idle: ['○', 'dim'], fail: ['✗', 'hot'] }

function sessionState(s) {
  const kind = own(JOB_KIND, s.job_state) ? JOB_KIND[s.job_state] : own(STATUS_KIND, s.status) ? STATUS_KIND[s.status] : 'ask'
  const label = own(JOB_LABEL, s.job_state) ? JOB_LABEL[s.job_state] : own(STATUS_LABEL, s.status) ? STATUS_LABEL[s.status] : s.status
  return { kind, label, mark: KIND_VIEW[kind][0], tone: KIND_VIEW[kind][1] }
}

function sessionCell(sessions, selfSid, hidden = new Set()) {
  const head = [S('세션', 'label'), S(' ')]
  if (!sessions) return [...head, FAIL()]
  const kinds = sessions.filter(s => s.sid !== selfSid && !hidden.has(s.sid)).map(s => sessionState(s).kind)
  const parts = ['work', 'idle', 'ask', 'fail'].map(k => [KIND_VIEW[k], kinds.filter(x => x === k).length])
    .filter(p => p[1]).map(([[m, t], c]) => [S(m + c, t)])
  return parts.length ? [...head, ...joinSegs(parts, () => S(' '))] : null
}

// NEVER: 세션 줄의 [숨김]·[제거] 버튼을 줄 끝에 두지 않는다. 줄 끝 detail 은 clip 으로 잘려 버튼이 사라질 수 있다(개정 20).
const ACT = (act, sid, text) => ({ text, tone: 'btn', act, sid })

function padCells(s, w) {
  const total = cellWidth(s)
  if (total <= w) return s + ' '.repeat(w - total)
  let out = '', cw = 0
  for (const ch of s) {
    const c = cellWidth(ch)
    if (cw + c > w - 1) break
    out += ch
    cw += c
  }
  return out + '…' + ' '.repeat(Math.max(0, w - cw - 1))
}

// NEVER: [제거] 조건을 register.js 의 확정 검사와 따로 바꾸지 않는다(같은 조건이다: 쉬는 중(status idle) · 잡이 작업 중 아님 · 잡 id 를 다른 세션과 같이 쓰지 않음).
const BTN_COL = 13 // WHY: «[숨김] [제거]» = 6 + 1 + 6
const NAME_MAX = 20
const NAME_MIN = 8
const STATE_KEEP = 16
const ACT_MIN = 6
function sessionRows(sessions, selfSid, hidden = new Set(), confirmSid = null, width = 200) {
  const rank = x => (x.self ? 0 : x.kind === 'work' ? 1 : x.kind === 'ask' ? 2 : 3)
  const shown = sessions.filter(s => !hidden.has(s.sid) || s.sid === selfSid)
  const items = shown.map(s => ({ s, self: s.sid === selfSid, ...sessionState(s) }))
    .sort((a, b) => rank(a) - rank(b) || (a.s.name < b.s.name ? -1 : a.s.name > b.s.name ? 1 : 0))
  const n = sessions.filter(s => s.sid !== selfSid && hidden.has(s.sid)).length
  if (!items.length && !n) return []
  const nameOf = x => (x.self ? x.s.name + '*' : x.s.name)
  const nameCell = (x, w) => (x.self && cellWidth(nameOf(x)) > w ? padCells(padCells(x.s.name, w - 1).trimEnd() + '*', w) : padCells(nameOf(x), w))
  const showBtn = width >= BTN_COL + 7
  const BC = showBtn ? BTN_COL : 4
  const natural = Math.min(NAME_MAX, Math.max(4, ...items.map(x => cellWidth(nameOf(x)))))
  const LW = Math.max(4, ...items.map(x => cellWidth(x.label || '')))
  const hasAct = items.some(x => x.s.job_detail || (!x.self && confirmSid === x.s.sid))
  const room = (withState, act) => width - BC - 3 - (act ? 2 + ACT_MIN : 0) - (withState ? 2 + LW : 0)
  const withState = room(true, hasAct) >= Math.min(STATE_KEEP, natural)
  const act = hasAct && room(withState, true) >= Math.min(NAME_MIN, natural)
  const NW = Math.max(4, Math.min(natural, room(withState, act)))
  const head = [S(padCells('세션', BC), 'label'), S('   '), S(padCells('이름', NW), 'label'),
    ...(withState ? [TWO(), S(padCells('상태', LW), 'label')] : []), ...(act ? [TWO(), S('활동', 'label')] : [])]
  const rows = items.map(x => {
    const { s, self, kind, label, mark, tone } = x
    const removable = s.job && s.status === 'idle' && s.job_state !== 'working' && !sessions.some(o => o.sid !== s.sid && o.job === s.job)
    const confirming = !self && confirmSid === s.sid
    const btns = !showBtn || self ? [S(' '.repeat(BC))]
      : confirming ? [ACT('rmok', s.sid, '[확정]'), S(' '), ACT('cancel', s.sid, '[취소]')]
        : [ACT('hide', s.sid, '[숨김]'), S(' '), removable ? ACT('rm', s.sid, '[제거]') : S('      ')]
    // WHY: 확정 대기 줄은 지울 잡 id 를 같이 보인다(security 2026-10-23: 앞부분이 같은 이름이 잘려 같아 보이면 엉뚱한 세션을 고를 수 있다).
    const detail = !act ? [] : confirming ? [S(`제거할까요? 잡 ${s.job || '?'}`, 'hot')] : s.job_detail ? [S(s.job_detail)] : []
    const cells = [...btns, S(' '), S(mark, tone), S(' '), S(nameCell(x, NW), self ? 'self' : kind === 'idle' ? 'dim' : 'base'),
      ...(withState ? [TWO(), S(padCells(label || '', LW), tone)] : []), ...(detail.length ? [TWO(), ...detail] : [])]
    const last = cells[cells.length - 1]
    if (!detail.length && last && !last.act) cells[cells.length - 1] = { ...last, text: last.text.trimEnd() }
    return clip(cells, width)
  })
  if (n && showBtn) rows.push([ACT('unhide', 'all', '[되돌리기]'), S(' '), S(`숨긴 세션 ${n}`, 'dim')])
  return [clip(head, width), ...rows]
}

function freeCell(mem, disk, level) {
  const head = [S('여유', 'label'), S(' ')]
  const showDisk = level < 9 || (!!disk && freeTone(disk) === 'hot')
  if (!mem && (!disk || !showDisk)) return [...head, FAIL()]
  const val = f => f
    ? [S(level >= 2 ? fmtG(f.avail) : `${Math.round(f.avail / GB)}/${fmtG(f.total)}`, freeTone(f))]
    : [FAIL()]
  if (level >= 11 && showDisk &&!(mem && freeTone(mem) !== 'base')) return [...head, S('디스크', 'label'), S(' '), ...val(disk)]
  const out = [...head, ...(level < 6 ? [S('메모리', 'label'), S(' ')] : []), ...val(mem)]
  if (showDisk) out.push(S(' · ', 'dim'), S('디스크', 'label'), S(' '), ...val(disk))
  return out
}

function modelCell(work, level, collapsed = false) {
  const items = [['Codex', work.codex], ['Grok', work.grok]].flatMap(([name, list]) => (list || []).map(m => [name, m]))
  if (!items.length) return null
  if (collapsed) return [S(`작업${items.length}`, 'runBold')]
  const groups = items.map(([name, m]) => {
    const model = level >= 2 && m.model ? m.model.replace(/^(gpt|grok)-/, '') : m.model
    const body = (level >= 5 ? [m.effort] : [model, m.effort]).filter(Boolean).join('/')
    return [S(name, 'runBold'), ...(body ? [S(' '), S(body)] : [])]
  })
  return joinSegs(groups, TWO)
}

export function shortName(name) {
  const parts = name.split('-')
  const i = parts.findIndex(p => /^[A-Za-z]\d/.test(p))
  return i < 0 ? name : parts.slice(i).join('-')
}

const doneOverMax = r => (r.done === null ? (r.max_epochs === null ? null : `?/${r.max_epochs}`)
  : r.max_epochs === null ? String(r.done) : `${r.done}/${r.max_epochs}`)

function groupRuns(runs) {
  const groups = [], byGpu = new Map()
  for (const r of runs) {
    let g = r.gpu === null ? null : byGpu.get(r.gpu)
    if (!g) { g = []; groups.push(g); if (r.gpu !== null) byGpu.set(r.gpu, g) }
    g.push(r)
  }
  return groups
}

const groupWatcher = g => (g.some(r => r.watcher === false) ? false : g.some(r => r.watcher === true) ? true : null)

function runItem(group, level) {
  const out = [S('GPU' + (group[0].gpu === null ? '?' : String(group[0].gpu))), S(' ' + group.length)]
  const w = groupWatcher(group)
  if (w === true) out.push(S(' ◉', 'ok'))
  else if (w === false) out.push(S(level >= 3 ? ' ✗' : ' 와쳐✗', 'hot'))
  return out
}

function trainCell(serverTrain, workTrain, level) {
  const head = [S('학습', 'label'), S(' ')]
  if (!serverTrain && !workTrain) return [...head, FAIL()]
  const e = level >= 3 || !workTrain ? 0 : workTrain.ended.length
  const parts = []
  if (serverTrain) {
    if (serverTrain.length) {
      parts.push(level >= 5 ? [S(`실행${serverTrain.length}`, 'run'), ...(serverTrain.some(r => r.watcher === false) ? [S(' ✗', 'hot')] : [])]
        : joinSegs(groupRuns(serverTrain).map(g => runItem(g, level)), TWO))
    }
  } else {
    const r = workTrain.running.length
    if (r) parts.push([S(level >= 1 ? `실행${r}` : `${r}판 실행`, 'run')])
  }
  if (e) parts.push([S(level >= 1 ? `종료${e}` : `${e}판 종료`, 'dim')])
  if (!parts.length) return null
  return [...head, ...joinSegs(parts, level >= 1 ? () => S(' ') : () => S(' · ', 'dim'))]
}

function blockCell(blocks, level) {
  if (typeof blocks !== 'number' || blocks < 1) return null
  if (level >= 4 && blocks < 10) return null
  return [S('차단', 'label'), S(' '), S(String(blocks), blocks >= 10 ? 'hot' : 'warn')]
}

// NEVER: ✔ ◼ ◻ 를 쓰지 않는다. 터미널이 두 칸으로 그리는데 셀 폭 계산은 한 칸이라 뒤 숫자를 덮었다(개정 23). 글자로 쓴다.
function todoCell(todos) {
  if (!todos || todos.doing + todos.open < 1) return null
  return [S('할 일', 'label'), S(' '), S('완료', 'dim'), S(String(todos.done), 'ok'), S(' '), S('진행', 'dim'), S(String(todos.doing), 'run'),
    S(' '), S('남음', 'dim'), S(String(todos.open), 'warn')]
}

function workRow(work, server, selfSid, limit, hidden) {
  return fit(level => {
    const cells = [modelCell(work, level, true), trainCell(server.train, work.train, level), blockCell(work.blocks, level)].filter(Boolean)
    if (!cells.length) cells.push([S('이상 없음', 'dim')])
    const tail = level < 6 ? [todoCell(work.todos), sessionCell(server.sessions, selfSid, hidden)].filter(Boolean) : []
    return [S(' 작업 ', 'workBadge'), S(' '), ...joinSegs([...cells, ...tail], SEP)]
  }, limit, 6)
}

function serverRow(server, limit) {
  return fit(level => {
    const gpu = gpuCell(server.gpus, level), free = freeCell(server.mem, server.disk, level)
    const front = level >= 13 && !!server.disk && freeTone(server.disk) === 'hot'
    return [S(' 서버 ', 'srvBadge'), S(' '), ...joinSegs(front ? [free, gpu] : [gpu, free], SEP)]
  }, limit, 13)
}

function chunk(arr, n) {
  const out = []
  for (let i = 0; i < arr.length; i += n) out.push(arr.slice(i, i + n))
  return out
}

function runRow(r, first) {
  const head = [...(first ? [S('학습', 'label'), S(' ')] : [S('     ')]), S('GPU' + (r.gpu === null ? '?' : r.gpu)), S(' '), S(shortName(r.name), 'run')]
  const ep = doneOverMax(r)
  if (ep !== null) head.push(TWO(), S(ep))
  if (r.watcher !== null) head.push(TWO(), r.watcher ? S('와쳐', 'ok') : S('와쳐 없음', 'hot'))
  head.push(TWO(), r.last ? S('last', 'ok') : S('last 없음', 'dim'))
  return head
}

const MIN_COL = 24
export function effectiveSplit(columns, split) {
  const half = Math.floor((columns - 4 - 3) / 2)
  if (!num(split) || half < MIN_COL) return 0
  return Math.max(MIN_COL - half, Math.min(half - MIN_COL, Math.round(split)))
}

function todoRows(todos, open, width) {
  if (!todos || todos.done + todos.doing + todos.open < 1) return []
  const btn = todos.items.length ? [S('  '), ACT('todos', 'toggle', open ? '[접기]' : '[펼치기]')] : []
  const head = [S('할 일', 'label'), S(' '), S('완료 ', 'dim'), S(String(todos.done), 'ok'), S(' · ', 'dim'), S('진행 ', 'dim'), S(String(todos.doing), 'run'),
    S(' · ', 'dim'), S('남음 ', 'dim'), S(String(todos.open), 'warn'), ...btn]
  const rows = [clip(head, width)]
  if (open) todos.items.forEach(x => rows.push(clip([S('      '), S(x.state === 'doing' ? '●' : '○', x.state === 'doing' ? 'run' : 'warn'), S(' '), S(x.subject)], width)))
  return rows
}

// WHY: 조회 결과(jira_comment.py mine --json)는 외부 글이라 입구에서 정화한다: 키는 JIRA_KEY 꼴만, 제목·상태는 제어 문자를 지우고 칸 수로 자른다.
// NEVER: 버튼 둘([작업]·[댓글 초안])로 게시·수정하지 않는다. 입력창을 채울 뿐이다(Jira 게시는 jira_comment.py preview → 사용자 승인 → post 절차 밖에서 하지 않는다).
export const JIRA_KEY = /^[A-Z][A-Z0-9]+-\d+$/
const MAX_JIRA = 10
export function cleanJira(j) {
  if (!isObj(j)) return null
  const items = (Array.isArray(j.items) ? j.items : []).filter(x => isObj(x) && typeof x.key === 'string' && JIRA_KEY.test(x.key))
    .slice(0, MAX_JIRA).map(x => ({ key: x.key, status: cut(typeof x.status === 'string' ? x.status : '', 20), summary: cut(typeof x.summary === 'string' ? x.summary.replace(/[«»]/g, '') : '', 80) }))
  return { open: j.open === true, loading: j.loading === true, error: typeof j.error === 'string' && j.error ? cut(j.error, 80) : null, items: Array.isArray(j.items) ? items : null }
}

const JIRA_BTN = (act, key, text) => ({ text, tone: 'btn', act, sid: key, key: `band-jira-${act}-${key}` })

function jiraRows(j, width) {
  if (!j) return []
  const n = j.items ? j.items.length : 0
  const info = !j.open ? '내 이슈' : j.error ? '' : j.items ? `내 이슈 ${n}` : j.loading ? '불러오는 중…' : ''
  const rows = [clip([S('Jira', 'label'), S(' '), ...(info ? [S(info, 'dim'), S('  ')] : []), ACT('jira', 'toggle', j.open ? '[접기]' : '[펼치기]')], width)]
  if (!j.open) return rows
  if (j.error) rows.push(clip([S('      '), S(`Jira 조회 실패: ${j.error}`, 'hot')], width))
  else if (j.items && !j.items.length) rows.push(clip([S('      '), S('배정된 미완료 이슈가 없습니다', 'dim')], width))
  else if (j.items) {
    const both = width >= 30, work = width >= 19
    j.items.forEach(x => rows.push(clip([
      ...(work ? [JIRA_BTN('work', x.key, '[작업]'), S(' ')] : []), ...(both ? [JIRA_BTN('draft', x.key, '[댓글 초안]'), S(' ')] : []),
      S(x.key, 'run'), S(' '), ...(x.status ? [S(`[${x.status}]`, 'dim'), S(' ')] : []), S(x.summary)], width)))
  }
  return rows
}

function detailRows(work, server, selfSid, buttons, limit, split, hidden, confirmSid, todosOpen = false, jira = null, login = null) {
  const half = Math.floor((limit - 3) / 2)
  const leftW = half + effectiveSplit(limit + 4, split), rightW = 2 * half - leftW
  const btns = typeof buttons === 'function' ? buttons(rightW) : buttons
  const RES = btns && btns.length ? lineWidth(btns) + 1 : 0
  const CONT = S('  ')
  const workBodies = []
  const m = modelCell(work, 0)
  if (m) workBodies.push(m)
  const tb = [blockCell(work.blocks, 0)]
  if (server.train && server.train.length) {
    server.train.forEach((r, i) => workBodies.push(runRow(r, i === 0)))
    const e = work.train ? work.train.ended.length : 0
    if (e) tb.unshift([S('     '), S(`${e}판 종료`, 'dim')])
  } else tb.unshift(trainCell(server.train, work.train, 0))
  if (tb.filter(Boolean).length) workBodies.push(joinSegs(tb.filter(Boolean), SEP))
  if (!workBodies.length) workBodies.push([S('이상 없음', 'dim')])
  const todo = todoRows(work.todos, todosOpen, leftW)
  if (todo.length) workBodies.push([], ...todo)
  const jr = jiraRows(jira, leftW)
  if (jr.length) workBodies.push([], ...jr)
  const table = server.sessions ? sessionRows(server.sessions, selfSid, hidden, confirmSid, leftW) : [[S('세션', 'label'), S(' '), FAIL()]]
  if (table.length) workBodies.push([], ...table)
  const lg = login && leftW - 7 >= 2 ? [S(' '), ...clip([S(login.text, login.tone)], leftW - 7)] : []
  const left = [[S(' 작업 ', 'workBadge'), ...lg], ...workBodies]

  const bodies = []
  if (!server.gpus) bodies.push([S('GPU', 'label'), S(' '), FAIL()])
  else {
    const items = [...server.gpus].sort((a, b) => a.i - b.i).map(g => isIdleGpu(g)
      ? [S(String(g.i), 'dim'), S(' ', 'dim'), S(`${g.util}%`, 'dim'), S(' ', 'dim'), S(`${mibG(g.used)}/${fmtMiB(g.total)}`, 'dim')]
      : gpuItem(g, 0))
    let per = 1
    for (const n of [3, 2]) if (chunk(items, n).every(c => 4 + lineWidth(joinSegs(c, TWO)) <= rightW)) { per = n; break }
    chunk(items, per).forEach((c, i) => bodies.push([...(i ? [S('    ')] : [S('GPU', 'label'), S(' ')]), ...joinSegs(c, TWO)]))
  }
  bodies.push([])
  if (server.disks) {
    bodies.push([S('여유', 'label'), S(' '), S('메모리', 'label'), S(' '), ...(server.mem
      ? [S(`${Math.round(server.mem.avail / GB)}/${fmtG(server.mem.total)}`, freeTone(server.mem))] : [FAIL()])])
    bodies.push([])
    server.disks.forEach((d, i) => bodies.push([i ? S('       ') : S('디스크 ', 'label'), S(d.kind, 'label'), S(' '), S(d.dev),
      ...(d.mount ? [S(' '), S(d.mount)] : []), S(' '), S(`${Math.round(d.avail / GB)}/${fmtG(d.total)}`, freeTone(d))]))
  } else bodies.push(freeCell(server.mem, server.disk, 0))
  const right = [rightW - RES >= 6 ? [S(' 서버 ', 'srvBadge')] : [], ...bodies]
  const wrap = (row, w, colW) => {
    const [head, rest] = splitAt(row, w)
    if (!rest.length) return [row]
    rest[0] = { ...rest[0], text: rest[0].text.trimStart() }
    return [head, clip([CONT, ...rest], colW)]
  }
  const rows = []
  for (let i = 0; i < Math.max(left.length, right.length); i++) {
    const ls = i < left.length ? wrap(left[i], leftW, leftW) : [], rs = i < right.length ? wrap(right[i], i === 0 ? rightW - RES : rightW, rightW) : []
    for (let j = 0; j < Math.max(ls.length, rs.length); j++) {
      const l = ls[j] || [], pad = leftW - lineWidth(l)
      rows.push([...l, ...(pad > 0 ? [S(' '.repeat(pad))] : []), { ...SEP(), divider: true }, ...(rs[j] || [])])
    }
  }
  if (btns && btns.length) rows[0] = [...rows[0], ...btns]
  return rows
}

// WHY: 띠 Box 의 좌우 여백 1칸씩 때문에 쓸 수 있는 폭은 columns - 4 다.
const GAP = n => ({ text: ' '.repeat(n), tone: 'base', button: true, spacer: true })
const CHIP = (text, key) => ({ text: ` ${text} `, tone: 'btn', button: true, key })
const onOffBlock = (label, on, key) => [CHIP(`${label} ${on ? 'on' : 'off'}`, key), GAP(on ? 2 : 1)]
export function buildBand({ work: rawWork, server: rawServer, selfSid, columns, expanded, split = 0, hidden = new Set(), confirmSid = null, big = false, todosOpen = false, maskOn = true, mobileOn = false, jira = null, news = '', newsState = 'max', login = null }) {
  const { work, server } = sanitize(rawServer, rawWork)
  const limit = columns - 4
  const button = CHIP(expanded ? '접기 ▾' : '상세 ▸', 'band-toggle')
  const maskBlock = onOffBlock('🔒 마스킹', maskOn, 'band-mask')
  const mobileBlock = onOffBlock('📱 모바일', mobileOn, 'band-mobile')
  if (expanded) {
    const bigBlock = [CHIP(big ? '작게 ⇲' : '크게 ⇱', 'band-big'), GAP(1)]
    const newsBlock = news ? [CHIP(news, 'band-news'), GAP(1)] : []
    const detailButtons = w => {
      for (const [withNews, withMobile, withBig, withMask] of [[true, true, true, true], [false, true, true, true], [false, false, true, true], [false, false, false, true]]) {
        const b = [...(withNews ? newsBlock : []), ...(withMobile ? mobileBlock : []), ...(withMask ? maskBlock : []), ...(withBig ? bigBlock : []), button]
        if (lineWidth(b) + 1 <= w) return b
      }
      return [button]
    }
    return detailRows(work, server, selfSid, detailButtons, limit, split, hidden, confirmSid, todosOpen, cleanJira(jira), login)
  }
  const tier = COLLAPSED_TIERS.find(t => limit >= tierReserve(t) + MIN_WORK) || COLLAPSED_TIERS[COLLAPSED_TIERS.length - 1]
  const reserve = tierReserve(tier)
  const newsOnOff = onOffBlock('📰', newsState !== 'off', 'band-news-toggle')
  return [[...clip(workRow(work, server, selfSid, limit - reserve, hidden), limit - reserve), ...(tier[0] ? newsOnOff : []), ...(tier[1] ? mobileBlock : []), ...(tier[2] ? maskBlock : []), button], clip(serverRow(server, limit), limit), ...(login ? [clip([S(login.text, login.tone)], limit)] : [])]
}

export const MIN_HEIGHT = 4
// NEVER: maxRows 를 터미널 높이로 넓히지 않는다. 엔진은 maxRows 보다 큰 트리를 그 칸 크기 창으로 넘겨 보여 줘서 화면에 더 나오지 않고 고정한 첫 줄까지 밀렸다(개정 22 에서 넓혔다가 개정 23 에서 되돌림).
export function windowBand(rows, { height = 0, offset = 0, maxRows = 12 } = {}) {
  const cap = Math.max(1, num(maxRows) ? Math.floor(maxRows) : 12)
  const body = rows.slice(1)
  const auto = Math.min(cap, rows.length + 1)
  const H = num(height) && height > 0 ? Math.max(Math.min(MIN_HEIGHT, cap), Math.min(cap, Math.round(height))) : auto
  const handle = H >= 3
  const win = Math.max(0, H - 1 - (handle ? 1 : 0))
  const maxOff = Math.max(0, body.length - win)
  const off = Math.max(0, Math.min(maxOff, num(offset) ? Math.round(offset) : 0))
  const visible = body.slice(off, off + win)
  const pad = Array.from({ length: Math.max(0, win - visible.length) }, () => [S(''), { ...SEP(), divider: true }])
  return { rows: [rows[0], ...visible, ...pad], height: H, offset: off, maxOffset: maxOff, total: body.length, win, handle, cap,
    auto: !(num(height) && height > 0), big: num(height) && height >= BIG_HEIGHT }
}
export const padRows = n => Array.from({ length: Math.max(0, n) }, () => [S(''), { ...SEP(), divider: true }])

// WHY: 상한보다 큰 수를 저장해 두면 windowBand 가 그때그때의 상한(이 세션의 최대 높이)으로 자른다(개정 21).
export const BIG_HEIGHT = 10000
