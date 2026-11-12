// 띠 데이터 → 줄(세그먼트 배열). 순수 함수만 둔다(시험: tests/band.test.ts).
// 세그먼트 = { text, tone }. tone: label base run runBold ok ask warn hot no noBadge workBadge srvBadge sep dim self btn (view.js 가 팔레트 색으로 바꾼다).
// 규칙의 정본: intent/2026-10-15-harness-mods.md 개정 5·6-3·7, 시안 .scratch/0a1b2c3d/band_design/design.md 최종본.
// 개정 13(2026-10-17): 접힌 띠 학습 칸은 판 이름 없이 GPU 별 `GPU2 (1/3/5)/60`, Codex·Grok 은 `작업N`. 펼친 보기는 판마다 GPU 라벨을 반복하고
// last 유무를 판 줄에 두며, 왼쪽 «작업» · 오른쪽 «서버» 로 반을 가른다(정본: intent 개정 13).
// 개정 15(2026-10-21): 접힌 띠 학습 칸은 GPU 별 «도는 판 수»만 `GPU5 3 ◉`(판이 여럿이면 에폭 묶음이 무엇이 몇 개 도는지 가렸다).
// 에폭 진행은 펼친 보기의 판 줄에만 두고, 펼친 보기에서 지표(val metric)·체크포인트 줄을 뺀다. 좌우 경계는 끌어서 옮긴다(split, 셀 수).
// GPU 메모리 G 는 MiB/1024 반올림(46080→45G), 메모리·디스크 G 는 바이트/2^30 반올림이다(시안의 46G 와 1 차이).
import { cellWidth, clip, lineWidth, splitAt } from './width.js'

const GB = 2 ** 30
// 개정 27(2026-10-23 사용자 지시 «상세/접기 버튼의 좌측에 여백 두고 별도 버튼»): 첫 줄 오른쪽에 화면 마스킹 켬/끔 버튼(2026-11-02 «🔒 마스킹 on/off»)을 «상세/접기» 앞에 둔다.
// 2026-11-02(사용자 결정 N2 + 위치 정정): 접힌 띠 오른쪽 버튼 무리에 뉴스 켬/끔 버튼(«📰 on»/«📰 off»)을 펼친 띠 band-news 와 같은 자리에 둔다.
// 2026-11-03(intent/2026-11-03-band-button-chips-mobile-toggle.md): 버튼마다 글자 앞뒤 한 칸 여백을 넣은 배경색 칩(view.js 가 칠한다)으로 구분하고,
// 뉴스 다음에 «📱 모바일 on/off» 버튼을 더했다(순서: 뉴스 → 모바일 → 마스킹 → 상세). 켬/끔 버튼은 글자가 바뀌어도 폭이 같도록 «on» 은 뒤 여백 2, «off» 는 1을 둔다.
// 폭은 칩 여백을 포함한다: 📰 칩 7/8 · 📱 칩 14/15 · 🔒 칩 14/15 · «상세 ▸» 칩 8 (이모지 2칸, 한글 2칸).
export const NEWS_RESERVE = 9      // «📰 on»(칩 7)+2 / «📰 off»(칩 8)+1
export const MOBILE_RESERVE = 16   // «📱 모바일 on»(칩 14)+2 / «📱 모바일 off»(칩 15)+1
export const MASK_RESERVE = 16     // «🔒 마스킹 on»(칩 14)+2 / «🔒 마스킹 off»(칩 15)+1
export const TOGGLE_RESERVE = 9    // «상세 ▸»(칩 8) + 앞 간격 1. 가장 좁은 폭에서도 남는 최소 예약
export const BTN_RESERVE = NEWS_RESERVE + MOBILE_RESERVE + MASK_RESERVE + TOGGLE_RESERVE // 접힌 띠 첫 행 오른쪽 전체
export const DETAIL_BTN_RESERVE = MOBILE_RESERVE + MASK_RESERVE + 9 + TOGGLE_RESERVE // 펼친 보기 첫 줄 오른쪽 전체(뉴스 제외): 모바일 · 마스킹 · «크게 ⇱»(칩 8)+1 · «접기 ▾»(8) + 앞 간격 1. 오른쪽 반이 모자라면 detailButtons 가 줄인다
export const MIN_RESERVE = TOGGLE_RESERVE
const MIN_WORK = 14 // 접힌 띠 작업 줄 최소 폭(종전과 같다)
// 접힌 띠 단계: [뉴스, 모바일, 마스킹]. 좁아지면 마스킹 → 모바일 → 뉴스 순으로 빠지고 «상세 ▸» 는 끝까지 남는다.
const COLLAPSED_TIERS = [[true, true, true], [true, true, false], [true, false, false], [false, false, false]]
const tierReserve = ([n, m, k]) => TOGGLE_RESERVE + (n ? NEWS_RESERVE : 0) + (m ? MOBILE_RESERVE : 0) + (k ? MASK_RESERVE : 0)
const MAX_CELLS = 40 // 캐시에서 온 문자열의 셀 폭 상한
const MAX_DETAIL = 120 // 세션 작업 한 줄(detail)의 셀 폭 상한

// ---- 입구 정화: 캐시·수집기 값은 신뢰하지 않는다(검수 security 1). 문자열은 제어·양방향 제어를 지우고 40칸으로 자른다.
// 숫자는 유한하지 않으면 그 항목을 null(조회 실패)로 본다. 이 아래의 계산은 정화된 값만 받는다.
// 지울 글자: C0·C1 제어, 줄/문단 구분(U+2028·U+2029), 양방향 제어(U+202A~U+202E, U+2066~U+2069). 소스에 글자를 직접 넣지 않고 코드 값으로 판정한다.
// 개정 21(security 2026-10-23): 폭 없는 글자(U+200B~U+200F, U+2060, U+FEFF)와 아랍 글자 표지(U+061C)도 지운다.
// 이름에 넣으면 세션 표에서 다른 세션과 같은 이름처럼 보이게 만들 수 있다([제거] 대상 혼동).
// 개정 22(security 2026-10-23): U+00AD · U+2061~2064 · U+206A~206F · U+FE00~FE0F · U+E0000~E007F · U+3164 도 지운다.
// 수집기 band_work_collect.py 의 _STRIP_RANGES 와 같은 집합이다(STRIP_RANGES 를 내보내 시험이 대조한다).
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

// 디스크 장치별 목록(개정 14): 수집기 disks. 숫자가 아니거나 Infinity·음수인 항목, 장치 이름이 빈 항목은 그 항목만 버리고, 종류는 SSD·HDD 외엔 «?». 최대 8장치, 하나도 없으면 null(호환: 루트 디스크 한 줄).
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

// job_state/job_detail: 수집기가 jobs/<id>/state.json 에서 꺼낸 두 값(개정 11). 형식이 틀리면 null, detail 은 120칸까지.
const JOB_STATE_OK = /^[a-z_]{1,20}$/
const JOB_OK = /^[0-9a-f]{8}$/   // 개정 20: «제거» 버튼이 `claude rm <잡 id>` 에 넘기는 값이라 8자리 16진만
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

// 서버 전체 GPU 위 학습 판(수집기 train). 정수가 아닌 gpu·max_epochs 는 null, 체크포인트는 {정수 epoch, 유한 수 또는 null} 만 최대 20개.
const int = v => (num(v) && Number.isInteger(v) && v >= 0 ? v : null)

function cleanTrainRuns(list) {
  if (!Array.isArray(list)) return null
  return list.filter(isObj).slice(0, 16).map(r => ({
    gpu: int(r.gpu), name: typeof r.name === 'string' ? cut(r.name, 60) : '', max_epochs: int(r.max_epochs), done: int(r.done), metric: str(r.metric),
    ckpts: (Array.isArray(r.ckpts) ? r.ckpts : []).filter(c => isObj(c) && int(c.epoch) !== null)
      .map(c => ({ epoch: c.epoch, value: num(c.value) ? c.value : null })).sort((a, b) => a.epoch - b.epoch).slice(-20),
    last: r.last === true,
    watcher: r.watcher === true ? true : r.watcher === false ? false : null, // true 살아 있음 · false launch-set 판인데 와쳐 없음 · null launch-set 판 아님
  }))
}

// 할 일(개정 22): 수집기 todos = { done, doing, open, items: [{ state: doing|open, subject }] }. 개수는 0 이상 정수, 항목은 12개·60칸까지.
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

// fit: level 0 부터 올리며 폭 한도 안에 들어오는 첫 결과를 돌려준다. 끝까지 넘치면 마지막 단계(buildBand 가 clip 으로 자른다).
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
  if (level >= 12) { // GPU 칸 접기: 사용 GPU 중 가장 나쁜 색을 사용N 에 칠한다(줄 끝 자르기가 빨강 디스크를 잘라내지 않게)
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

// 세션 상태(개정 11): job_state(jobs/<id>/state.json)가 있으면 그것으로, 없으면 기존 status 로 분류한다. 상속 키(constructor 등)는 hasOwnProperty 로 막는다.
// kind: work ● 작업 중 · ask ◐ 입력 대기(또는 모르는 status) · idle ○ · fail ✗ 분홍.
const own = (o, k) => Object.prototype.hasOwnProperty.call(o, k)
// blocked 는 2026-10-16 실측 값으로, 잡이 사용자 답을 기다리는 상태다(needs_input 과 같게 본다).
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

// 접힌 띠의 세션 칸: 본인을 뺀 ●N ○M ◐K ✗J 개수만(이름은 펼친 보기에서만). 작업 줄 끝에 놓인다.
function sessionCell(sessions, selfSid, hidden = new Set()) {
  const head = [S('세션', 'label'), S(' ')]
  if (!sessions) return [...head, FAIL()]
  const kinds = sessions.filter(s => s.sid !== selfSid && !hidden.has(s.sid)).map(s => sessionState(s).kind)
  const parts = ['work', 'idle', 'ask', 'fail'].map(k => [KIND_VIEW[k], kinds.filter(x => x === k).length])
    .filter(p => p[1]).map(([[m, t], c]) => [S(m + c, t)])
  return parts.length ? [...head, ...joinSegs(parts, () => S(' '))] : null
}

// 펼친 보기의 세션 줄(한 세션 한 줄): `● [PRJ] Manager  작업 중  run_exp.py 추론 결과 확인`. 순서: 본인 → 작업 중 → 입력 대기 → 나머지, 같은 순위는 이름순.
// detail 은 줄 끝 세그먼트라 detailRows 의 clip 이 남은 폭에 맞춰 자른다.
// 개정 20: 이 세션이 아닌 줄 앞머리에 [숨김]·[제거] 버튼(작업 중 세션·잡 id 를 모르는 세션은 제거 없음). 제거를 누르면 그 줄만
// «제거할까요? [확정] [취소]» 로 바뀐다(confirmSid). 버튼을 줄 앞에 두는 까닭: 줄 끝 detail 은 clip 으로 잘려 버튼이 사라질 수 있다.
// 숨긴 세션(hidden, 모든 세션 띠 공통)은 빼고, 하나라도 있으면 끝에 «숨김 N [되돌리기]» 줄을 단다.
const ACT = (act, sid, text) => ({ text, tone: 'btn', act, sid })

// 셀 폭 w 에 맞춰 자르고(넘치면 …) 공백으로 채운다(세션 표의 열 맞춤).
function padCells(s, w) {
  const total = cellWidth(s)
  if (total <= w) return s + ' '.repeat(w - total)
  let out = '', cw = 0
  for (const ch of s) {          // 넘치면 «…» 1칸을 남기고 자른다
    const c = cellWidth(ch)
    if (cw + c > w - 1) break
    out += ch
    cw += c
  }
  return out + '…' + ' '.repeat(Math.max(0, w - cw - 1))
}

// 세션 표(개정 21, 2026-10-23 사용자 지시 «너무 난잡해 보이니까 표 형태로»): 머리 줄 + 세션마다 한 줄.
//   열: 버튼(13칸) · 상태 표시 · 이름 · 상태 · 활동. 머리 줄의 버튼 칸 자리에 «세션» 라벨을 두어 다른 묶음 라벨(학습 등)과 같은 자리에 선다.
//   버튼 칸: 본인은 공백, 확정 대기는 [확정] [취소](활동 칸에 «제거할까요?»), 그 밖은 [숨김] 과 조건이 맞으면 [제거].
//   폭(width, 배지 들여쓰기를 뺀 왼쪽 반 폭)에 맞춘다. 이름이 우선이다: 상태 열을 둔 채로 이름이 STATE_KEEP 칸(또는 가장 긴 이름)만큼
//   들어가지 않으면 상태 열을 뺀다(앞의 ●◐○✗ 가 같은 뜻). 그래도 이름이 NAME_MIN 칸이 안 되면 활동 자리 예약을 푼다.
//   한 세션은 한 줄이다: 넘치는 활동은 둘째 줄로 잇지 않고 …로 자른다(잇면 줄 가운데서 낱말이 끊겨 표가 흐트러진다).
// [제거] 조건은 register.js 의 확정 검사와 같다: 쉬는 중(status idle) · 잡이 작업 중 아님 · 잡 id 를 다른 세션과 같이 쓰지 않음.
const BTN_COL = 13 // «[숨김] [제거]» = 6 + 1 + 6
const NAME_MAX = 20
const NAME_MIN = 8
const STATE_KEEP = 16
const ACT_MIN = 6  // 활동이 있는 세션이 하나라도 있으면 활동 열에 남겨 두는 폭
function sessionRows(sessions, selfSid, hidden = new Set(), confirmSid = null, width = 200) {
  const rank = x => (x.self ? 0 : x.kind === 'work' ? 1 : x.kind === 'ask' ? 2 : 3)
  const shown = sessions.filter(s => !hidden.has(s.sid) || s.sid === selfSid)
  const items = shown.map(s => ({ s, self: s.sid === selfSid, ...sessionState(s) }))
    .sort((a, b) => rank(a) - rank(b) || (a.s.name < b.s.name ? -1 : a.s.name > b.s.name ? 1 : 0))
  const n = sessions.filter(s => s.sid !== selfSid && hidden.has(s.sid)).length
  if (!items.length && !n) return []   // 보일 세션이 없으면 머리 줄만 있는 빈 표를 그리지 않는다(qa 2026-10-23)
  const nameOf = x => (x.self ? x.s.name + '*' : x.s.name)
  // 본인 이름은 잘려도 «*» 를 남긴다(qa 2026-10-23: 80열에서 «[Harness] Ma…» 로 본인 표시가 사라졌다).
  const nameCell = (x, w) => (x.self && cellWidth(nameOf(x)) > w ? padCells(padCells(x.s.name, w - 1).trimEnd() + '*', w) : padCells(nameOf(x), w))
  // 버튼 칸이 잘려 «[제…» 같은 버튼이 생기지 않게, 버튼 13칸 + « ● » + 이름 4칸이 안 들어가면 버튼 칸을 통째로 뺀다(qa 2026-10-23).
  const showBtn = width >= BTN_COL + 7
  const BC = showBtn ? BTN_COL : 4
  const natural = Math.min(NAME_MAX, Math.max(4, ...items.map(x => cellWidth(nameOf(x)))))
  const LW = Math.max(4, ...items.map(x => cellWidth(x.label || '')))
  const hasAct = items.some(x => x.s.job_detail || (!x.self && confirmSid === x.s.sid))
  const room = (withState, act) => width - BC - 3 - (act ? 2 + ACT_MIN : 0) - (withState ? 2 + LW : 0) // 이름 열 자리
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
    // 활동 열이 없을 만큼 좁으면 활동은 싣지 않는다(확정 대기는 [확정] [취소] 버튼이 이미 보인다).
    // 확정 대기 줄은 지울 잡 id 를 같이 보인다(security 2026-10-23: 앞부분이 같은 이름이 잘려 같아 보이면 엉뚱한 세션을 고를 수 있다).
    const detail = !act ? [] : confirming ? [S(`제거할까요? 잡 ${s.job || '?'}`, 'hot')] : s.job_detail ? [S(s.job_detail)] : []
    const cells = [...btns, S(' '), S(mark, tone), S(' '), S(nameCell(x, NW), self ? 'self' : kind === 'idle' ? 'dim' : 'base'),
      ...(withState ? [TWO(), S(padCells(label || '', LW), tone)] : []), ...(detail.length ? [TWO(), ...detail] : [])]
    // 줄 끝 공백은 지운다(활동이 없는 줄이 폭 끝까지 공백으로 차지 않게).
    const last = cells[cells.length - 1]
    if (!detail.length && last && !last.act) cells[cells.length - 1] = { ...last, text: last.text.trimEnd() }
    return clip(cells, width)
  })
  if (n && showBtn) rows.push([ACT('unhide', 'all', '[되돌리기]'), S(' '), S(`숨긴 세션 ${n}`, 'dim')])
  return [clip(head, width), ...rows]
}

function freeCell(mem, disk, level) {
  const head = [S('여유', 'label'), S(' ')]
  const showDisk = level < 9 || (!!disk && freeTone(disk) === 'hot') // 빨강 디스크는 줄여도 숨기지 않는다
  if (!mem && (!disk || !showDisk)) return [...head, FAIL()]
  const val = f => f
    ? [S(level >= 2 ? fmtG(f.avail) : `${Math.round(f.avail / GB)}/${fmtG(f.total)}`, freeTone(f))]
    : [FAIL()]
  // 마지막 단계(11)에서도 빨강 디스크가 보이는 경우, 메모리가 정상이면 메모리를 접어 디스크가 줄 끝에서 잘리지 않게 한다.
  if (level >= 11 && showDisk &&!(mem && freeTone(mem) !== 'base')) return [...head, S('디스크', 'label'), S(' '), ...val(disk)]
  const out = [...head, ...(level < 6 ? [S('메모리', 'label'), S(' ')] : []), ...val(mem)]
  if (showDisk) out.push(S(' · ', 'dim'), S('디스크', 'label'), S(' '), ...val(disk))
  return out
}

// collapsed(접힌 띠): 모델·effort 대신 호출 수만 `작업N`. 펼친 보기는 모델·effort 를 level 에 맞춰 적는다.
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

// 판 짧은 이름: «영문자 다음 숫자» 로 시작하는 첫 조각부터 끝까지(exp-demo-1a-x72-1t → x72-1t). 없으면 전체.
export function shortName(name) {
  const parts = name.split('-')
  const i = parts.findIndex(p => /^[A-Za-z]\d/.test(p))
  return i < 0 ? name : parts.slice(i).join('-')
}

// 끝낸 에폭(1부터 센 개수, last.ckpt 의 epoch+1)을 최대 에폭과 함께: 17/60, 최대를 모르면 17, 끝낸 수를 모르면 ?/60, 둘 다 모르면 null.
const doneOverMax = r => (r.done === null ? (r.max_epochs === null ? null : `?/${r.max_epochs}`)
  : r.max_epochs === null ? String(r.done) : `${r.done}/${r.max_epochs}`)

// 같은 GPU 위 판끼리 묶는다(입력은 (gpu, name) 순). gpu 를 모르는 판(null)은 각각 따로.
function groupRuns(runs) {
  const groups = [], byGpu = new Map()
  for (const r of runs) {
    let g = r.gpu === null ? null : byGpu.get(r.gpu)
    if (!g) { g = []; groups.push(g); if (r.gpu !== null) byGpu.set(r.gpu, g) }
    g.push(r)
  }
  return groups
}

// 묶음 와쳐: 하나라도 false 면 false, 아니면 non-null 이 있고 전부 true 면 true, 아니면 null.
const groupWatcher = g => (g.some(r => r.watcher === false) ? false : g.some(r => r.watcher === true) ? true : null)

// GPU 묶음의 접힌 표기(개정 15): 판 이름·에폭 없이 그 GPU 에서 도는 판 수만 `GPU3 2`. 모든 단계에서 GPU 접두와 개수를 유지한다.
// gpu 를 모르는 판(null)은 groupRuns 가 판마다 따로 묶으므로 `GPU? 1` 로 하나씩 보인다.
function runItem(group, level) {
  const out = [S('GPU' + (group[0].gpu === null ? '?' : String(group[0].gpu))), S(' ' + group.length)]
  // 와쳐(개정 11): 살아 있으면 ◉(민트), launch-set 판인데 없으면 와쳐✗(분홍, 폭이 모자라면 ✗ 로 줄이되 지우지 않는다), launch-set 판이 아니면 표시 없음.
  const w = groupWatcher(group)
  if (w === true) out.push(S(' ◉', 'ok'))
  else if (w === false) out.push(S(level >= 3 ? ' ✗' : ' 와쳐✗', 'hot'))
  return out
}

// 서버 전체의 학습 판(server.train)을 보인다. server.train 이 null 이면 현재 저장소의 work.train.running 개수로 대신하고(조회 실패 방지),
// 종료 개수는 항상 work.train.ended(현재 저장소)다. 둘 다 null 이면 «(조회 실패)».
function trainCell(serverTrain, workTrain, level) {
  const head = [S('학습', 'label'), S(' ')]
  if (!serverTrain && !workTrain) return [...head, FAIL()]
  const e = level >= 3 || !workTrain ? 0 : workTrain.ended.length
  const parts = []
  if (serverTrain) {
    if (serverTrain.length) {
      parts.push(level >= 5 ? [S(`실행${serverTrain.length}`, 'run'), ...(serverTrain.some(r => r.watcher === false) ? [S(' ✗', 'hot')] : [])] // ◉ 는 빠져도 와쳐 없음 경보는 남긴다
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

// 1단계에는 게이트 차단 데이터가 없어 work.blocks 가 숫자일 때만 칸이 생긴다.
function blockCell(blocks, level) {
  if (typeof blocks !== 'number' || blocks < 1) return null
  if (level >= 4 && blocks < 10) return null
  return [S('차단', 'label'), S(' '), S(String(blocks), blocks >= 10 ? 'hot' : 'warn')]
}

// 할 일 개수 칸(개정 22, 사용자 지시 «할일 목록 접었을 때는 완료 및 진행 중과 남은 항목이 보이도록»): «할 일 완료32 진행2 남음2».
// 개정 23(사용자 지적 «특수기호와 숫자가 겹쳐 보여»): ✔ ◼ ◻ 는 터미널이 두 칸으로 그리는데 셀 폭 계산은 한 칸이라 뒤 숫자를 덮었다. 글자로 쓴다.
// 진행·남은 것이 없으면 칸을 만들지 않는다(완료만 쌓인 목록은 볼 일이 없다).
function todoCell(todos) {
  if (!todos || todos.doing + todos.open < 1) return null
  return [S('할 일', 'label'), S(' '), S('완료', 'dim'), S(String(todos.done), 'ok'), S(' '), S('진행', 'dim'), S(String(todos.doing), 'run'),
    S(' '), S('남음', 'dim'), S(String(todos.open), 'warn')]
}

// 세션 칸은 작업 줄 끝(학습·차단 칸 뒤)에 둔다(개정 11). 사다리 0~5 는 앞 칸들이 줄고, 6 에서 할 일·세션 칸이 숨는다.
// 세션 칸만 있고 이상 칸이 없으면 «이상 없음» 을 앞에 둔다(세션은 이상이 아니다).
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
    // 마지막 수단(13): 빨강 디스크가 있으면 여유 칸을 GPU 칸 앞으로 옮겨 줄 끝에서 잘리지 않게 한다.
    const front = level >= 13 && !!server.disk && freeTone(server.disk) === 'hot'
    return [S(' 서버 ', 'srvBadge'), S(' '), ...joinSegs(front ? [free, gpu] : [gpu, free], SEP)]
  }, limit, 13)
}

function chunk(arr, n) {
  const out = []
  for (let i = 0; i < arr.length; i += n) out.push(arr.slice(i, i + n))
  return out
}

// 펼친 보기의 판 한 줄(개정 15: 지표·체크포인트 줄을 뺐다). 첫 판 줄에만 «학습» 라벨을 달고(뒤 판은 같은 폭 공백),
// 같은 GPU 의 판도 줄마다 GPU 라벨을 반복한다(트리·들여쓰기 없음, 개정 13). 에폭 진행(17/60)은 이 줄에서만 보인다.
function runRow(r, first) {
  const head = [...(first ? [S('학습', 'label'), S(' ')] : [S('     ')]), S('GPU' + (r.gpu === null ? '?' : r.gpu)), S(' '), S(shortName(r.name), 'run')]
  const ep = doneOverMax(r) // 17/60 · 끝낸 수 모름 ?/60 · 최대 모름 17 · 둘 다 모름이면 생략. 짧은 이름·«에폭» 접미 없음
  if (ep !== null) head.push(TWO(), S(ep))
  // 와쳐 있음/없음(개정 11) 뒤에 last 있음/없음(개정 13). launch-set 판이 아니면(null) 와쳐 표시만 없다.
  if (r.watcher !== null) head.push(TWO(), r.watcher ? S('와쳐', 'ok') : S('와쳐 없음', 'hot'))
  head.push(TWO(), r.last ? S('last', 'ok') : S('last 없음', 'dim'))
  return head
}

// 좌우 경계 위치(개정 15): split 은 기본 경계(반 폭)에서 왼쪽 반을 몇 칸 넓혔는지(음수면 좁힘)다. 양쪽 반이 MIN_COL 칸보다
// 좁아지지 않게 자르고, 그 폭이 안 나오는 좁은 터미널에서는 0(가운데)이다. 오른쪽 반 = 2×반 폭 − 왼쪽(split 0 이면 종전과 같은 폭).
// register.js 가 끌기 메시지를 받을 때도 같은 함수로 잘라 저장하므로, 저장값이 한계 밖으로 밀려 다음 끌기가 헛도는 일이 없다.
const MIN_COL = 24
export function effectiveSplit(columns, split) {
  const half = Math.floor((columns - 4 - 3) / 2)
  if (!num(split) || half < MIN_COL) return 0
  return Math.max(MIN_COL - half, Math.min(half - MIN_COL, Math.round(split)))
}

// 펼친 보기(개정 13·15): 왼쪽 = «작업»(모델 호출·학습 판·차단·세션), 오른쪽 = «서버»(GPU·여유), 가운데 ` │ ` 한 칸(divider 표시: view.js 가 끌 수 있는 경계로 그린다).
// 왼쪽 폭 leftW = 반 폭 + split, 오른쪽 폭 rightW = 2×반 폭 − leftW. 넘치면 둘째 줄로 이어 쓰고(최대 2줄, 둘째 줄도 넘치면 …), 줄 수가 다르면 빈 쪽을 공백(왼쪽)·빈 줄(오른쪽)로 맞춘다. 버튼은 합친 첫 줄 끝.
// 할 일 묶음(개정 22·23): 머리 줄 «할 일 완료 N · 진행 N · 남음 N [펼치기|접기]», 펼치면 진행 → 남은순으로 항목마다 한 줄.
// 엔진의 할 일 목록은 mod 가 다시 그릴 자리가 없어(렌더 훅 없음) ctrl+t 로 숨기고, 띠의 이 묶음으로 본다. 펼침 여부는 register.js 가 $.store 에 둔다.
function todoRows(todos, open, width) {
  if (!todos || todos.done + todos.doing + todos.open < 1) return []
  const btn = todos.items.length ? [S('  '), ACT('todos', 'toggle', open ? '[접기]' : '[펼치기]')] : []
  // 개정 23: ✔ ◼ ◻ 대신 글자와 ●(진행) ○(남음). ●○ 는 세션 표에서도 쓰는 한 칸 글자다.
  const head = [S('할 일', 'label'), S(' '), S('완료 ', 'dim'), S(String(todos.done), 'ok'), S(' · ', 'dim'), S('진행 ', 'dim'), S(String(todos.doing), 'run'),
    S(' · ', 'dim'), S('남음 ', 'dim'), S(String(todos.open), 'warn'), ...btn]
  const rows = [clip(head, width)]
  if (open) todos.items.forEach(x => rows.push(clip([S('      '), S(x.state === 'doing' ? '●' : '○', x.state === 'doing' ? 'run' : 'warn'), S(' '), S(x.subject)], width)))
  return rows
}

// Jira 이슈 묶음(개정 27, intent 2026-10-23): 할 일 묶음과 같은 꼴로 머리 줄 «Jira 내 이슈 N [펼치기|접기]», 펼치면 이슈마다 한 줄.
// 조회 결과(jira_comment.py mine --json)는 외부 글이라 입구에서 정화한다: 키는 JIRA_KEY 꼴만, 제목·상태는 제어 문자를 지우고 칸 수로 자른다.
// 버튼 둘([작업]·[댓글 초안])은 입력창을 채울 뿐이다. 게시·수정은 하지 않는다(Jira 게시는 jira_comment.py preview → 사용자 승인 → post 절차 밖에서 하지 않는다).
// 버튼은 줄 앞에 둔다: 줄 끝 제목은 clip 으로 잘려 버튼이 사라질 수 있다(세션 표와 같은 이유).
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
    // 폭이 모자라면 [댓글 초안] 을, 더 모자라면 [작업] 도 뺀다(잘린 버튼 «[댓글 초…» 이 생기지 않게).
    const both = width >= 30, work = width >= 19
    j.items.forEach(x => rows.push(clip([
      ...(work ? [JIRA_BTN('work', x.key, '[작업]'), S(' ')] : []), ...(both ? [JIRA_BTN('draft', x.key, '[댓글 초안]'), S(' ')] : []),
      S(x.key, 'run'), S(' '), ...(x.status ? [S(`[${x.status}]`, 'dim'), S(' ')] : []), S(x.summary)], width)))
  }
  return rows
}

function detailRows(work, server, selfSid, buttons, limit, split, hidden, confirmSid, todosOpen = false, jira = null) {
  // buttons 는 배열이거나 오른쪽 반 폭을 받아 배열을 돌려주는 함수(좁으면 버튼을 줄인다, detailButtons).
  const half = Math.floor((limit - 3) / 2)
  const leftW = half + effectiveSplit(limit + 4, split), rightW = 2 * half - leftW
  const btns = typeof buttons === 'function' ? buttons(rightW) : buttons
  const RES = btns && btns.length ? lineWidth(btns) + 1 : 0   // 버튼이 없으면(시험용 호출) 첫 줄도 끝까지 쓴다
  // 개정 26(2026-10-23 사용자 지시 «학습과 서버 일부 정보가 같이 들어가니까 한 줄씩 내리고 "        할 일"가 아니라 "할 일"»):
  // 첫 줄(고정)은 « 작업 »·« 서버 » 배지와 크게·접기 버튼만 두고, 내용은 둘째 줄부터 들여쓰기 없이 쓴다. 넘쳐 이어 쓰는 줄만 2칸 들여쓴다.
  const CONT = S('  ')
  const workBodies = []
  const m = modelCell(work, 0)
  if (m) workBodies.push(m)
  const tb = [blockCell(work.blocks, 0)]
  if (server.train && server.train.length) { // 판마다 한 줄. 종료 개수는 현재 저장소 기준 그대로.
    server.train.forEach((r, i) => workBodies.push(runRow(r, i === 0)))
    const e = work.train ? work.train.ended.length : 0
    if (e) tb.unshift([S('     '), S(`${e}판 종료`, 'dim')]) // «학습» 라벨은 첫 판 줄에 이미 있어 판 이름 칸에 맞춰 들여쓴다
  } else tb.unshift(trainCell(server.train, work.train, 0))
  if (tb.filter(Boolean).length) workBodies.push(joinSegs(tb.filter(Boolean), SEP))
  if (!workBodies.length) workBodies.push([S('이상 없음', 'dim')])
  // 할 일 묶음은 학습 뒤 · 세션 앞에 빈 줄로 나눠 둔다(개정 22).
  const todo = todoRows(work.todos, todosOpen, leftW)
  if (todo.length) workBodies.push([], ...todo)
  // Jira 이슈 묶음(개정 27)은 할 일 묶음 뒤 · 세션 앞에 같은 꼴로 둔다.
  const jr = jiraRows(jira, leftW)
  if (jr.length) workBodies.push([], ...jr)
  // 세션 표는 작업 부분 끝에 둔다(개정 11). «세션» 라벨은 표의 머리 줄에 있다(개정 21).
  // 학습 묶음과 세션 표 사이에 빈 줄 하나(개정 21, 2026-10-23 사용자 지시 «학습과 세션 사이에 개행»).
  const table = server.sessions ? sessionRows(server.sessions, selfSid, hidden, confirmSid, leftW) : [[S('세션', 'label'), S(' '), FAIL()]]
  if (table.length) workBodies.push([], ...table)
  const left = [[S(' 작업 ', 'workBadge')], ...workBodies]

  const bodies = []
  if (!server.gpus) bodies.push([S('GPU', 'label'), S(' '), FAIL()])
  else {
    const items = [...server.gpus].sort((a, b) => a.i - b.i).map(g => isIdleGpu(g)
      ? [S(String(g.i), 'dim'), S(' ', 'dim'), S(`${g.util}%`, 'dim'), S(' ', 'dim'), S(`${mibG(g.used)}/${fmtMiB(g.total)}`, 'dim')]
      : gpuItem(g, 0))
    // 반 폭이 좁아 GPU 가 잘리지 않도록 한 줄 GPU 수를 3 → 1 로 줄인다(머리 «GPU » 4칸. 개정 26 부터 버튼은 배지 줄에 있어 GPU 줄은 반 폭을 다 쓴다).
    let per = 1
    for (const n of [3, 2]) if (chunk(items, n).every(c => 4 + lineWidth(joinSegs(c, TWO)) <= rightW)) { per = n; break }
    chunk(items, per).forEach((c, i) => bodies.push([...(i ? [S('    ')] : [S('GPU', 'label'), S(' ')]), ...joinSegs(c, TWO)]))
  }
  // GPU · 여유 메모리 · 디스크 묶음 사이마다 빈 줄 하나(개정 21, 2026-10-23 사용자 지시).
  bodies.push([])
  if (server.disks) { // 개정 14: 메모리 한 줄 + 디스크 장치마다 한 줄(첫 줄만 «디스크» 라벨). 수집기가 SSD → HDD → ? 순으로 이미 정렬해 둔다.
    bodies.push([S('여유', 'label'), S(' '), S('메모리', 'label'), S(' '), ...(server.mem
      ? [S(`${Math.round(server.mem.avail / GB)}/${fmtG(server.mem.total)}`, freeTone(server.mem))] : [FAIL()])])
    bodies.push([])
    server.disks.forEach((d, i) => bodies.push([i ? S('       ') : S('디스크 ', 'label'), S(d.kind, 'label'), S(' '), S(d.dev),
      ...(d.mount ? [S(' '), S(d.mount)] : []), S(' '), S(`${Math.round(d.avail / GB)}/${fmtG(d.total)}`, freeTone(d))]))
  } else bodies.push(freeCell(server.mem, server.disk, 0)) // disks 가 없거나 비면 종전처럼 루트 디스크 한 줄(호환)
  // 첫 줄 오른쪽은 배지만 둔다. 버튼 자리를 빼고 배지가 들어갈 폭이 없을 만큼 좁으면 배지를 빼서 쪼개진 배지가 둘째 줄로 밀리지 않게 한다(qa 2026-10-23, 44열).
  const right = [rightW - RES >= 6 ? [S(' 서버 ', 'srvBadge')] : [], ...bodies]
  // 반마다 폭(왼쪽 leftW, 오른쪽 rightW, 첫 줄 오른쪽은 버튼 자리를 뺀 폭)을 넘으면 …로 자르지 않고 둘째 줄에 2칸 들여쓰기로 이어 쓴다(둘째 줄도 넘치면 그때 …).
  // 같은 논리 행의 두 반은 줄 번호끼리 합치고, 한쪽이 모자라면 왼쪽은 공백 leftW칸·오른쪽은 빈 줄로 맞춘다. 왼쪽은 leftW 까지 공백으로 채워 구분선을 세로로 맞춘다.
  const wrap = (row, w, colW) => {
    const [head, rest] = splitAt(row, w)
    if (!rest.length) return [row]
    rest[0] = { ...rest[0], text: rest[0].text.trimStart() } // 이어 쓰는 줄은 들여쓰기 바로 뒤에 글자가 오도록 앞 공백을 뗀다
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

// 띠 Box 의 좌우 여백 1칸씩 때문에 쓸 수 있는 폭은 columns - 4 다.
// hidden: 숨긴 세션 sid 집합(개정 20, 모든 세션 띠 공통). confirmSid: «제거할까요?» 를 띄울 세션.
// big: 띠가 최대 높이인지(개정 21: «크게» 는 창이 아니라 띠를 이 세션의 최대 높이로, 다시 누르면 «작게» 로 원래 높이).
// maskOn: 화면 마스킹 켬(개정 27): 첫 줄 오른쪽 «🔒 마스킹 on/off» 버튼의 글자. jira: { open, loading, error, items } — null 이면 Jira 묶음을 그리지 않는다.
// 버튼 순서(왼쪽 → 오른쪽): 펼침 [뉴스] · [모바일] · [마스킹] · [크게/작게] · [접기], 접힘 [뉴스] · [모바일] · [마스킹] · [상세]. 사이는 빈 칸(spacer)이다.
// mobileOn: 모바일 모드 켬(2026-11-03): 버튼 글자 «📱 모바일 on/off». 정본은 decision-popup 이 쓰는 파일이고 register.js 가 읽어 넘긴다.
const GAP = n => ({ text: ' '.repeat(n), tone: 'base', button: true, spacer: true })
const CHIP = (text, key) => ({ text: ` ${text} `, tone: 'btn', button: true, key }) // 칩: 글자 앞뒤 한 칸 여백(배경색은 view.js)
const onOffBlock = (label, on, key) => [CHIP(`${label} ${on ? 'on' : 'off'}`, key), GAP(on ? 2 : 1)] // 글자가 바뀌어도 폭이 같다
export function buildBand({ work: rawWork, server: rawServer, selfSid, columns, expanded, split = 0, hidden = new Set(), confirmSid = null, big = false, todosOpen = false, maskOn = true, mobileOn = false, jira = null, news = '', newsState = 'max' }) {
  const { work, server } = sanitize(rawServer, rawWork)
  const limit = columns - 4
  const button = CHIP(expanded ? '접기 ▾' : '상세 ▸', 'band-toggle')
  const maskBlock = onOffBlock('🔒 마스킹', maskOn, 'band-mask')
  const mobileBlock = onOffBlock('📱 모바일', mobileOn, 'band-mobile')
  if (expanded) {
    const bigBlock = [CHIP(big ? '작게 ⇲' : '크게 ⇱', 'band-big'), GAP(1)]
    // 뉴스 줄 보기 버튼(news 가 비어 있지 않을 때만, 크게·작게·끔 순환).
    const newsBlock = news ? [CHIP(news, 'band-news'), GAP(1)] : []
    // 오른쪽 반이 모자라면 [뉴스] → [모바일] → [크게] → [마스킹] 순으로 빼고, 마지막에는 [접기] 만 남긴다(접기는 어떤 폭에서도 남는다).
    // 배지(« 서버 », detailRows 가 자리가 없으면 뺀다)보다 버튼이 먼저다: 80열에서는 칩 폭 때문에 배지가 빠지고 마스킹 · 크게 · 접기가 남는다.
    const detailButtons = w => {
      for (const [withNews, withMobile, withBig, withMask] of [[true, true, true, true], [false, true, true, true], [false, false, true, true], [false, false, false, true]]) {
        const b = [...(withNews ? newsBlock : []), ...(withMobile ? mobileBlock : []), ...(withMask ? maskBlock : []), ...(withBig ? bigBlock : []), button]
        if (lineWidth(b) + 1 <= w) return b
      }
      return [button]
    }
    return detailRows(work, server, selfSid, detailButtons, limit, split, hidden, confirmSid, todosOpen, cleanJira(jira))
  }
  const tier = COLLAPSED_TIERS.find(t => limit >= tierReserve(t) + MIN_WORK) || COLLAPSED_TIERS[COLLAPSED_TIERS.length - 1]
  const reserve = tierReserve(tier)
  // 뉴스 켬/끔 버튼: 켬(크게·작게)이면 «📰 on», 끔이면 «📰 off».
  const newsOnOff = onOffBlock('📰', newsState !== 'off', 'band-news-toggle')
  return [[...clip(workRow(work, server, selfSid, limit - reserve, hidden), limit - reserve), ...(tier[0] ? newsOnOff : []), ...(tier[1] ? mobileBlock : []), ...(tier[2] ? maskBlock : []), button], clip(serverRow(server, limit), limit)]
}

// 펼친 보기 높이 창(개정 20, 사용자 지시 «상태창 자체의 세로폭을 조절» · «스크롤을 내려도 우측 상단 접기는 항상»).
// 첫 줄(배지·크게·접기 버튼)은 고정하고 나머지(body)만 offset 부터 win 줄을 보인다. 맨 위 조절 줄 1줄을 더해 전체 높이 = height.
// height 가 0·null 이면 자동(내용 전부 + 조절 줄, 엔진 상한 maxRows 안). 지정 높이가 내용보다 크면 빈 줄로 채워 그만큼 덮는다.
// 엔진은 maxRows 보다 큰 트리를 자기 창으로 스크롤해 첫 줄까지 밀어 올리므로, 트리를 maxRows 안에 두고 넘기기는 직접 한다(ui.scroll).
// 상한(cap)이 4줄보다 작은 아주 낮은 화면에서도 트리가 상한을 넘지 않게 한다(qa 2026-10-23): H = cap, 창은 0줄까지 줄고,
// H < 3 이면 조절 줄을 그리지 않는다(handle: false). 그때도 첫 줄(접기 버튼)은 남는다.
export const MIN_HEIGHT = 4
// maxRows 는 엔진이 띠에 실제로 보여 주는 줄 수(다른 그림 줄 제외)다. 개정 22 에서 터미널 높이로 넓혔다가 개정 23 에서 되돌렸다:
// 엔진은 maxRows 보다 큰 트리를 그 칸 크기 창으로 넘겨 보여 줘서 화면에 더 나오지 않고 고정한 첫 줄까지 밀렸다.
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
// 보이지 않는 채움 줄 n개(개정 25): 경계 칸(divider)을 가진 빈 줄이라 세 칸 배치가 깨지지 않는다.
export const padRows = n => Array.from({ length: Math.max(0, n) }, () => [S(''), { ...SEP(), divider: true }])

// «크게» 의 높이 값(개정 21): 상한보다 큰 수를 저장해 두면 windowBand 가 그때그때의 상한(이 세션의 최대 높이)으로 자른다.
export const BIG_HEIGHT = 10000
