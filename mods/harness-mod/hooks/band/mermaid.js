// Mermaid → ASCII 도해 변환기(순수 함수 모듈: $ 없음, 외부 패키지 없음). 배선은 register.js 쪽 몫이다.
// 판단 근거: 모델이 보는 원문은 바꾸지 않고 화면만 바꾼다.
//   못 읽는 문법은 원문 그대로가 안전하다(그래서 지원 밖이면 null 을 돌려 호출자가 원문을 둔다).
//   외부 설치 없이 자체 구현, 2026-10-23 사용자 결정(intent/2026-10-23-mods-jira-mermaid-mask-typo.md).
// 지원: flowchart/graph(TD·TB·LR, BT·RL 은 TD·LR 로 취급)와 sequenceDiagram 기본 문법. 노드 모양은 모두 상자로 그린다.
import { cellWidth } from './width.js'

const MAX_NODES = 60
const MAX_EDGES = 120
const MAX_SRC = 20000 // 원문 글자 수 상한
const MAX_LINE = 500 // 한 줄 글자 수 상한
const SHORT_LABEL = 12 // 이 칸 수 이하의 간선 라벨만 선 옆에 붙이고, 더 길면 아래 목록으로 보낸다
const P = 1, N = 2, A = 4, B = 8 // 층축 앞·뒤, 교차축 낮은·높은 쪽(TD 에서는 위·아래·왼·오른)
const GLYPH = [' ', '│', '│', '│', '─', '┘', '┐', '┤', '─', '└', '┌', '├', '─', '┴', '┬', '┼'] // 방향 마스크 U1 D2 L4 R8 → 선 글자

// ---- 글자판: 글자(리터럴)와 선 마스크를 따로 두고, 그릴 때 리터럴이 마스크를 이긴다 ----
function makeCanvas() {
  const ch = [], mk = []
  return {
    mask(x, y, m) { if (x < 0 || y < 0 || !m) return; (mk[y] || (mk[y] = []))[x] = ((mk[y] || [])[x] || 0) | m },
    put(x, y, s) {
      if (x < 0 || y < 0) return
      const r = ch[y] || (ch[y] = [])
      let c = x
      for (const g of s) { r[c] = g; if (cellWidth(g) === 2) { r[c + 1] = ''; c += 2 } else c += 1 }
    },
    at(x, y) { return (ch[y] || [])[x] },
    free(x, y, len) { // 라벨 둘레 한 칸까지 비었는지
      if (x < 0 || y < 0) return false
      for (let i = Math.max(0, x - 1); i <= x + len; i++) if ((ch[y] && ch[y][i] !== undefined) || (mk[y] && mk[y][i])) return false
      return true
    },
    lines() {
      const out = []
      for (let y = 0; y < Math.max(ch.length, mk.length); y++) {
        const a = ch[y] || [], b = mk[y] || []
        let s = ''
        for (let x = 0; x < Math.max(a.length, b.length); x++) s += a[x] !== undefined ? a[x] : (b[x] ? GLYPH[b[x]] : ' ')
        out.push(s.replace(/\s+$/, ''))
      }
      while (out.length && !out[out.length - 1]) out.pop()
      return out
    },
  }
}

// ---- 글 정리 ----
function cleanLabel(t) {
  return String(t).trim().replace(/^"([\s\S]*)"$/, '$1').replace(/^`([\s\S]*)`$/, '$1')
    .replace(/<br\s*\/?>/gi, ' ').replace(/<\/?(b|i|u|em|strong|span|small|sub|sup|code|p|div)\b[^>]*>/gi, '')
    .replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ').trim()
}

// 줄 앞 %% 주석 제거. 따옴표 안의 %% 는 거의 없으므로 단순 처리한다.
function stripComment(line) {
  const i = line.indexOf('%%')
  return (i >= 0 ? line.slice(0, i) : line).trim()
}

// 따옴표·괄호 밖의 ; 에서만 나눈다.
function splitStatements(line) {
  const out = []
  let depth = 0, q = false, cur = ''
  for (const c of line) {
    if (c === '"') q = !q
    else if (!q && '[({'.includes(c)) depth++
    else if (!q && '])}'.includes(c)) depth = Math.max(0, depth - 1)
    if (c === ';' && !q && depth === 0) { out.push(cur); cur = '' } else cur += c
  }
  out.push(cur)
  return out.map(s => s.trim()).filter(Boolean)
}

function wrapItems(prefix, items, max) {
  const out = []
  let cur = prefix, n = 0
  for (const it of items) {
    if (n && cellWidth(cur) + 1 + cellWidth(it) > max) { out.push(cur); cur = '   ' + ' ' + it; n = 1 } else { cur += ' ' + it; n++ }
  }
  out.push(cur)
  return out
}

// ---- flowchart 파서 ----
const ID = /[\p{L}\p{N}_]+/uy
const OPEN = [['([', '])'], ['[(', ')]'], ['[[', ']]'], ['((', '))'], ['{{', '}}'], ['[', ']'], ['(', ')'], ['{', '}'], ['>', ']']]
const FLOW_IGNORE = /^(subgraph|direction|classDef|class|style|linkStyle|click|accTitle|accDescr)\b|^end$/i

function parseNode(s, i, g) {
  ID.lastIndex = i
  const m = ID.exec(s)
  if (!m) return null
  const id = m[0]
  i += id.length
  let label
  const op = OPEN.find(([o]) => s.startsWith(o, i))
  if (op) {
    const [o, c] = op
    let j = i + o.length
    while (s[j] === ' ') j++
    let content
    if (s[j] === '"') {
      const q = s.indexOf('"', j + 1)
      if (q < 0) return null
      content = s.slice(j + 1, q)
      j = q + 1
      while (s[j] === ' ') j++
      if (!s.startsWith(c, j)) return null
      j += c.length
    } else {
      const k = s.indexOf(c, j)
      if (k < 0) return null
      content = s.slice(j, k)
      j = k + c.length
    }
    if (o === '[' && /^[\\/][\s\S]*[\\/]$/.test(content.trim())) content = content.trim().slice(1, -1)
    label = cleanLabel(content)
    i = j
  }
  const cls = /^:::[\w-]+/.exec(s.slice(i))
  if (cls) i += cls[0].length
  const node = g.nodes.get(id) || { label: '' }
  if (label) node.label = label
  g.nodes.set(id, node)
  return { id, i }
}

function parseGroup(s, i, g) {
  const ids = []
  for (;;) {
    const r = parseNode(s, i, g)
    if (!r || g.nodes.size > MAX_NODES) return null // 노드 수 상한은 만들면서 바로 센다
    ids.push(r.id)
    i = r.i
    let j = i
    while (s[j] === ' ') j++
    if (s[j] === '&') { i = j + 1; while (s[i] === ' ') i++ } else return { ids, i }
  }
}

const HEAD = { '>': 'arrow', x: 'x', o: 'o' }
function parseEdge(s, i) {
  const rest = s.slice(i)
  let m = /^(--|==|-\.)\s{1,8}([\s\S]*?)\s{1,8}(-{2,}|={2,}|\.+-)(>|x|o)?(?=\s|$)/.exec(rest)
  if (m) return { end: i + m[0].length, label: cleanLabel(m[2]), head: HEAD[m[4]] || 'none' }
  m = /^<?(-\.+-|={2,}|-{2,})(?:(>)|([xo])(?=[\s|]|$))?/.exec(rest)
  if (!m) return null
  let j = i + m[0].length
  const head = HEAD[m[2] || m[3]] || 'none'
  let label = ''
  while (s[j] === ' ') j++
  if (s[j] === '|') {
    const k = s.indexOf('|', j + 1)
    if (k < 0) return null
    label = cleanLabel(s.slice(j + 1, k))
    j = k + 1
  }
  return { end: j, label, head }
}

function parseStatement(s, g) {
  let r = parseGroup(s, 0, g)
  if (!r) return false
  let prev = r.ids, i = r.i
  for (;;) {
    while (s[i] === ' ') i++
    if (i >= s.length) return true
    const e = parseEdge(s, i)
    if (!e) return false
    i = e.end
    while (s[i] === ' ') i++
    r = parseGroup(s, i, g)
    if (!r) return false
    if (g.edges.length + prev.length * r.ids.length > MAX_EDGES) return false // 간선 곱이 상한을 넘으면 만들기 전에 중단
    for (const a of prev) for (const b of r.ids) g.edges.push({ from: a, to: b, label: e.label, head: e.head })
    prev = r.ids
    i = r.i
  }
}

// ---- flowchart 분석: 순환 간선 떼기 → 가장 긴 경로 층 → 층 안 순서(교차 줄이기) ----
function analyzeFlow(g) {
  const ids = [...g.nodes.keys()]
  const n = ids.length
  const idx = new Map(ids.map((id, i) => [id, i]))
  const text = ids.map(id => g.nodes.get(id).label || id)
  const edges = [], seen = new Map()
  for (const e of g.edges) {
    const f = idx.get(e.from), t = idx.get(e.to), k = f + ',' + t
    const prev = seen.get(k)
    if (prev) {
      if (!prev.label && e.label) prev.label = e.label
      else if (e.label && e.label !== prev.label) edges.push({ f, t, label: e.label, head: e.head, kind: 'dup' })
      continue
    }
    const c = { f, t, label: e.label, head: e.head, kind: 'draw' }
    seen.set(k, c)
    edges.push(c)
  }
  const live = e => e.kind === 'draw'
  const out = ids.map(() => []), inc = ids.map(() => [])
  for (const e of edges) if (live(e)) { out[e.f].push(e); inc[e.t].push(e) }
  const state = new Array(n).fill(0)
  const dfs = u => {
    state[u] = 1
    for (const e of out[u]) {
      if (state[e.t] === 1) e.kind = 'back'
      else if (state[e.t] === 0) dfs(e.t)
    }
    state[u] = 2
  }
  const starts = [...ids.keys()].sort((a, b) => (inc[a].length > 0) - (inc[b].length > 0))
  for (const u of starts) if (!state[u]) dfs(u)
  const lay = new Array(n).fill(-1)
  const calc = v => {
    if (lay[v] >= 0) return lay[v]
    let l = 0
    for (const e of inc[v]) if (live(e)) l = Math.max(l, calc(e.f) + 1)
    return (lay[v] = l)
  }
  for (let v = 0; v < n; v++) calc(v)
  for (const e of edges) if (live(e) && lay[e.t] - lay[e.f] !== 1) e.kind = 'skip'
  const L = Math.max(...lay) + 1
  const layers = Array.from({ length: L }, () => [])
  for (let v = 0; v < n; v++) layers[lay[v]].push(v)
  const up = ids.map(() => []), down = ids.map(() => [])
  for (const e of edges) if (live(e)) { up[e.t].push(e.f); down[e.f].push(e.t) }
  const posIn = new Array(n).fill(0)
  const reindex = l => layers[l].forEach((v, i) => { posIn[v] = i })
  layers.forEach((_, l) => reindex(l))
  const sortLayer = (l, nb) => {
    const key = v => (nb[v].length ? nb[v].reduce((s, w) => s + posIn[w], 0) / nb[v].length : posIn[v])
    const keys = new Map(layers[l].map(v => [v, key(v)]))
    layers[l].sort((a, b) => keys.get(a) - keys.get(b))
    reindex(l)
  }
  for (let it = 0; it < 4; it++) {
    for (let l = 1; l < L; l++) sortLayer(l, up)
    for (let l = L - 2; l >= 0; l--) sortLayer(l, down)
  }
  return { n, text, edges, layers, lay, up, down }
}

// ---- flowchart 그리기: 층축(main)과 교차축(cross)으로 계산하고 TD·LR 에 맞춰 글자판 좌표로 옮긴다 ----
function drawFlow(a, TD) {
  const { n, text, edges, layers, lay, up, down } = a
  const Ln = layers.length
  const tw = text.map(cellWidth)
  const cs = text.map((_, v) => (TD ? (tw[v] + 4) | 1 : 3)) // 교차축 크기(홀수라 가운데 칸이 정확히 있다)
  const half = v => (cs[v] - 1) / 2
  const gap = TD ? 3 : 1
  const mainSize = layers.map(ls => (TD ? 3 : Math.max(...ls.map(v => tw[v] + 4))))
  const cc = new Array(n).fill(0)
  const place = (l, want) => {
    let hi = null
    layers[l].forEach((v, i) => {
      let lo = Math.round(want[i] - half(v))
      if (hi !== null && lo < hi + gap + 1) lo = hi + gap + 1
      cc[v] = lo + half(v)
      hi = lo + cs[v] - 1
    })
  }
  layers.forEach((ls, l) => {
    place(l, ls.map(() => 0))
    const lo = cc[ls[0]] - half(ls[0]), hi = cc[ls[ls.length - 1]] + half(ls[ls.length - 1])
    const sh = -Math.round((lo + hi) / 2)
    ls.forEach(v => { cc[v] += sh })
  })
  const want = (v, nb) => (nb[v].length ? Math.round(nb[v].reduce((s, w) => s + cc[w], 0) / nb[v].length) : cc[v])
  for (let it = 0; it < 4; it++) {
    for (let l = 1; l < Ln; l++) place(l, layers[l].map(v => want(v, up)))
    for (let l = Ln - 2; l >= 0; l--) place(l, layers[l].map(v => want(v, down)))
  }
  const minLo = Math.min(...cc.map((c, v) => c - half(v)))
  for (let v = 0; v < n; v++) cc[v] -= minLo

  // 이웃 층 사이: 출발 노드별 묶음에 모선(bus) 줄을 배정하고, 라벨 자리(extra)를 잡아 간격을 정한다
  const gapInfo = []
  for (let l = 0; l < Ln - 1; l++) {
    const es = edges.filter(e => e.kind === 'draw' && lay[e.f] === l)
    const groups = new Map()
    for (const e of es) (groups.get(e.f) || groups.set(e.f, []).get(e.f)).push(e)
    const gl = [...groups.entries()].map(([f, list]) => {
      const cols = [cc[f], ...list.map(e => cc[e.t])]
      return { f, list, lo: Math.min(...cols), hi: Math.max(...cols), bus: list.length > 1 || cc[list[0].t] !== cc[f] }
    }).filter(x => x.bus).sort((x, y) => x.lo - y.lo)
    const rowEnd = []
    for (const x of gl) {
      let r = rowEnd.findIndex(h => h < x.lo - 1)
      if (r < 0) r = rowEnd.length
      rowEnd[r] = x.hi
      x.row = r
    }
    const rowOf = new Map(gl.map(x => [x.f, x.row]))
    const lbl = es.filter(e => e.label && cellWidth(e.label) <= SHORT_LABEL)
    const extra = lbl.length ? (TD ? 1 : Math.max(...lbl.map(e => cellWidth(e.label))) + 1) : 0
    gapInfo.push({ es, rowOf, K: rowEnd.length, extra, size: 1 + rowEnd.length + extra + 1 })
  }
  const ms = [0]
  for (let l = 0; l < Ln - 1; l++) ms.push(ms[l] + mainSize[l] + gapInfo[l].size)

  const cv = makeCanvas()
  const sw = b => (TD ? b : (b & 1 ? 4 : 0) | (b & 2 ? 8 : 0) | (b & 4 ? 1 : 0) | (b & 8 ? 2 : 0))
  const rx = (m, c) => (TD ? c : m), ry = (m, c) => (TD ? m : c)
  const mask = (m, c, b) => cv.mask(rx(m, c), ry(m, c), sw(b))
  const lit = (m, c, s) => cv.put(rx(m, c), ry(m, c), s)
  const vseg = (m1, m2, c) => { for (let m = m1; m <= m2; m++) mask(m, c, (m > m1 ? P : 0) | (m < m2 ? N : 0)) }
  const hseg = (m, c1, c2) => { const lo = Math.min(c1, c2), hi = Math.max(c1, c2); for (let c = lo; c <= hi; c++) mask(m, c, (c > lo ? A : 0) | (c < hi ? B : 0)) }

  layers.forEach((ls, l) => ls.forEach(v => {
    const w = TD ? cs[v] : mainSize[l], inner = w - 2
    const x0 = TD ? cc[v] - half(v) : ms[l], y0 = TD ? ms[l] : cc[v] - 1
    cv.put(x0, y0, '┌' + '─'.repeat(inner) + '┐')
    cv.put(x0, y0 + 1, '│ ' + text[v] + ' '.repeat(inner - 1 - tw[v]) + '│')
    cv.put(x0, y0 + 2, '└' + '─'.repeat(inner) + '┘')
  }))

  const headCh = { arrow: TD ? '▼' : '►', x: 'x', o: 'o' }
  const unplaced = []
  const sources = new Set()
  gapInfo.forEach((gi, l) => {
    const bm = ms[l] + mainSize[l] - 1, t = ms[l + 1]
    for (const e of gi.es) {
      const c0 = cc[e.f], c1 = cc[e.t]
      const row = gi.rowOf.get(e.f)
      sources.add(e.f)
      mask(bm + 1, c0, P)
      if (row === undefined) vseg(bm + 1, t - 1, c0)
      else { const y = bm + 2 + row; vseg(bm + 1, y, c0); hseg(y, c0, c1); vseg(y, t - 1, c1) }
      if (e.head === 'none') mask(t - 1, c1, N)
    }
    for (const e of gi.es) if (e.head !== 'none') lit(t - 1, cc[e.t], headCh[e.head])
    for (const e of gi.es) {
      if (!e.label) continue
      const len = cellWidth(e.label)
      let ok = false
      if (len <= SHORT_LABEL) {
        const cand = TD
          ? [[cc[e.t] + 2, t - 2], [cc[e.t] - 1 - len, t - 2], [cc[e.f] + 2, bm + 1], [cc[e.f] - 1 - len, bm + 1]]
          : [[t - 1 - len, cc[e.t] - 1], [bm + 2 + gi.K, cc[e.f] - 1]]
        for (const [x, y] of cand) {
          if (!TD && x + len > t - 1) continue
          if (cv.free(x, y, len)) { cv.put(x, y, e.label); ok = true; break }
        }
      }
      if (!ok) unplaced.push(e)
    }
  })
  for (const v of sources) {
    const l = lay[v]
    lit(ms[l] + mainSize[l] - 1, cc[v], TD ? '┬' : '├')
  }
  return { lines: cv.lines(), unplaced }
}

function flowNotes(a, unplaced) {
  const out = []
  for (const e of a.edges) {
    const s = `${a.text[e.f]} → ${a.text[e.t]}${e.label ? ' : ' + e.label : ''}`
    if (e.kind !== 'draw') out.push('↪ ' + s)
    else if (unplaced.includes(e)) out.push(s)
  }
  return out
}

function flowList(a, maxWidth) {
  const out = []
  a.layers.forEach((ls, i) => out.push(...wrapItems(`${i + 1}층:`, ls.map(v => `[${a.text[v]}]`), maxWidth)))
  for (const e of a.edges) out.push(`${e.kind === 'draw' ? '' : '↪ '}${a.text[e.f]} → ${a.text[e.t]}${e.label ? ' : ' + e.label : ''}`)
  return out
}

function renderFlow(stmts, header, maxWidth) {
  const g = { nodes: new Map(), edges: [] }
  for (const st of stmts) {
    if (FLOW_IGNORE.test(st)) continue
    if (!parseStatement(st, g)) return null
    if (g.nodes.size > MAX_NODES || g.edges.length > MAX_EDGES) return null
  }
  if (!g.nodes.size) return null
  const TD = !/^(LR|RL)$/i.test(header[2] || 'TD')
  const a = analyzeFlow(g)
  const d = drawFlow(a, TD)
  const lines = [...d.lines, ...flowNotes(a, d.unplaced)]
  if (Math.max(...lines.map(cellWidth)) > maxWidth) return flowList(a, maxWidth).join('\n')
  return lines.join('\n')
}

// ---- sequenceDiagram ----
const ARROWS = {
  '->>': { dash: false, head: '►' }, '-->>': { dash: true, head: '►' }, '->': { dash: false, head: '' }, '-->': { dash: true, head: '' },
  '-x': { dash: false, head: 'x' }, '--x': { dash: true, head: 'x' }, '-)': { dash: false, head: ')' }, '--)': { dash: true, head: ')' },
}
const MSG = /^([^\s:]+?)\s*(-->>|->>|--x|-x|--\)|-\)|-->|->)\s*[+-]?\s*([^\s:]+?)\s*(?::\s*(.*))?$/
const NOTE = /^note\s+(over|left of|right of)\s+([^:]+?)\s*:\s*(.*)$/i
const BLOCK = /^(loop|alt|opt|par|critical|break|else|and|option)\b\s*(.*)$/i

function parseSeq(stmts) {
  const parts = [], byId = new Map(), events = []
  const ensure = id => {
    if (!byId.has(id)) { const p = { id, name: id }; byId.set(id, p); parts.push(p) }
    return byId.get(id)
  }
  const stack = []
  let auto = false, count = 0
  for (const st of stmts) {
    let m
    if (/^autonumber\b/i.test(st)) { auto = !/\boff\b/i.test(st); continue }
    if (/^(activate|deactivate|title)\b/i.test(st)) continue
    if ((m = /^(?:participant|actor)\s+(\S+)(?:\s+as\s+(.+))?$/i.exec(st))) { ensure(m[1]).name = cleanLabel(m[2] || m[1]); continue }
    if ((m = NOTE.exec(st))) {
      const ids = m[2].split(',').map(s => s.trim()).filter(Boolean)
      if (!ids.length) return null
      ids.forEach(ensure)
      events.push({ t: 'note', kind: m[1].toLowerCase(), ids, text: cleanLabel(m[3]) })
      continue
    }
    if (/^rect\b/i.test(st)) { stack.push('rect'); continue }
    if (/^end$/i.test(st)) {
      if (stack.pop() !== 'rect') events.push({ t: 'block', text: '[end]' })
      continue
    }
    if ((m = BLOCK.exec(st))) {
      if (!/^(else|and|option)$/i.test(m[1])) stack.push('blk')
      events.push({ t: 'block', text: `[${m[1].toLowerCase()}${m[2] ? ' ' + cleanLabel(m[2]) : ''}]` })
      continue
    }
    if ((m = MSG.exec(st))) {
      ensure(m[1]); ensure(m[3])
      let text = cleanLabel(m[4] || '')
      if (auto) text = `${++count}.${text ? ' ' + text : ''}`
      events.push({ t: 'msg', from: m[1], to: m[3], arrow: ARROWS[m[2]], text })
      continue
    }
    return null
  }
  return parts.length && events.length ? { parts, events } : null
}

function drawSeq(sq) {
  const { parts, events } = sq
  const k = parts.length
  const index = new Map(parts.map((p, i) => [p.id, i]))
  const pw = parts.map(p => (cellWidth(p.name) + 4) | 1)
  const ph = pw.map(w => (w - 1) / 2)
  const pitch = []
  for (let i = 0; i < k - 1; i++) pitch.push(ph[i] + ph[i + 1] + 3)
  const reqs = []
  for (const e of events) {
    if (e.t !== 'msg') continue
    const i = index.get(e.from), j = index.get(e.to), len = cellWidth(e.text)
    if (i === j) { if (i < k - 1) reqs.push({ i, j: i + 1, n: len + 6 }) } else if (len) reqs.push({ i: Math.min(i, j), j: Math.max(i, j), n: len + 4 })
  }
  reqs.sort((x, y) => x.j - x.i - (y.j - y.i))
  for (const r of reqs) {
    let cur = 0
    for (let m = r.i; m < r.j; m++) cur += pitch[m]
    if (cur < r.n) pitch[r.j - 1] += r.n - cur
  }
  const cx = [ph[0]]
  for (let i = 1; i < k; i++) cx.push(cx[i - 1] + pitch[i - 1])
  const cv = makeCanvas()
  parts.forEach((p, i) => {
    const x0 = cx[i] - ph[i], inner = pw[i] - 2
    cv.put(x0, 0, '┌' + '─'.repeat(inner) + '┐')
    cv.put(x0, 1, '│ ' + p.name + ' '.repeat(inner - 1 - cellWidth(p.name)) + '│')
    cv.put(x0, 2, '└' + '─'.repeat(ph[i] - 1) + '┬' + '─'.repeat(ph[i] - 1) + '┘')
  })
  const fullW = cx[k - 1] + 1
  let y = 4
  for (const e of events) {
    if (e.t === 'block') {
      cv.put(0, y++, '-' + e.text + '-'.repeat(Math.max(2, fullW - 1 - cellWidth(e.text))))
    } else if (e.t === 'note') {
      const txt = `(${e.text})`, len = cellWidth(txt)
      const [a, b] = [cx[index.get(e.ids[0])], cx[index.get(e.ids[e.ids.length - 1])]]
      let x
      if (e.kind === 'over') x = Math.round((a + b - len) / 2)
      else if (e.kind === 'right of') x = a + 2
      else x = a - 1 - len
      cv.put(Math.max(0, x), y++, txt)
    } else {
      const i = index.get(e.from), j = index.get(e.to), ar = e.arrow
      const line = ar.dash ? '┄' : '─'
      if (i === j) {
        cv.put(cx[i], y, '├' + line + '┐' + (e.text ? ' ' + e.text : ''))
        cv.put(cx[i], y + 1, '┤' + (ar.head ? (ar.head === '►' ? '◄' : ar.head) : line) + '┘')
        y += 3
      } else {
        const lo = Math.min(cx[i], cx[j]), hi = Math.max(cx[i], cx[j])
        if (e.text) cv.put(lo + 1 + Math.floor((hi - lo - 1 - cellWidth(e.text)) / 2), y++, e.text)
        const right = i < j
        cv.put(cx[i], y, right ? '├' : '┤')
        for (let x = lo + 1; x < hi; x++) cv.put(x, y, line)
        if (ar.head) cv.put(right ? hi - 1 : lo + 1, y, right ? ar.head : (ar.head === '►' ? '◄' : ar.head))
        y += 2
      }
    }
  }
  for (let r = 3; r < y; r++) for (const c of cx) if (cv.at(c, r) === undefined) cv.put(c, r, '│')
  return cv.lines()
}

function seqList(sq) {
  const name = id => sq.parts.find(p => p.id === id).name
  const out = ['참여자: ' + sq.parts.map(p => p.name).join(', ')]
  for (const e of sq.events) {
    if (e.t === 'block') out.push(e.text)
    else if (e.t === 'note') out.push(`(${e.text}) : ${e.ids.map(name).join(', ')}`)
    else out.push(`${name(e.from)} ${e.arrow.dash ? '⇢' : '→'} ${name(e.to)}${e.text ? ' : ' + e.text : ''}`)
  }
  return out
}

function renderSeq(stmts, maxWidth) {
  const sq = parseSeq(stmts)
  if (!sq || sq.parts.length > MAX_NODES || sq.events.length > MAX_EDGES) return null
  const lines = drawSeq(sq)
  if (Math.max(...lines.map(cellWidth)) > maxWidth) return seqList(sq).join('\n')
  return lines.join('\n')
}

// ---- 공개 함수 ----

/** Mermaid 원문 → ASCII 도해 문자열. 지원 밖 문법·오류·크기 초과면 null. */
export function renderMermaid(src, maxWidth = 100) {
  try {
    if (typeof src !== 'string' || src.length > MAX_SRC) return null // 입력 상한: 큰 글은 변환하지 않고 원문을 둔다
    const max = Number.isFinite(maxWidth) && maxWidth > 0 ? maxWidth : 100
    let raw = src.split(/\r?\n/)
    if (raw.some(l => l.length > MAX_LINE)) return null
    const first = raw.findIndex(l => l.trim())
    if (first >= 0 && raw[first].trim() === '---') { // 앞머리(front matter) 건너뛰기
      const end = raw.findIndex((l, i) => i > first && l.trim() === '---')
      if (end < 0) return null
      raw = raw.slice(end + 1)
    }
    const lines = raw.map(stripComment).filter(Boolean)
    if (!lines.length) return null
    const flow = /^(flowchart|graph)(?:\s+(TD|TB|LR|RL|BT))?\s*;?$/i.exec(lines[0])
    if (flow) return renderFlow(lines.slice(1).flatMap(splitStatements), flow, max)
    if (/^sequenceDiagram\s*;?$/i.test(lines[0])) return renderSeq(lines.slice(1), max)
    return null
  } catch {
    return null
  }
}

/** 마크다운 속 ```mermaid 펜스를 ```text 도해 펜스로 바꾼다. 못 바꾼 블록과 나머지 글은 그대로, 바뀐 게 없으면 같은 문자열을 돌려준다. */
export function replaceMermaidBlocks(markdown, maxWidth = 100) {
  if (typeof markdown !== 'string' || !markdown.includes('mermaid')) return markdown
  const lines = markdown.split('\n')
  const out = []
  let changed = false
  for (let i = 0; i < lines.length; i++) {
    const open = /^(\s*)(`{3,}|~{3,})\s*(\S*)/.exec(lines[i])
    if (!open) { out.push(lines[i]); continue }
    const [, indent, fence, info] = open
    let end = -1
    for (let j = i + 1; j < lines.length; j++) {
      const c = /^\s*(`{3,}|~{3,})\s*$/.exec(lines[j])
      if (c && c[1][0] === fence[0] && c[1].length >= fence.length) { end = j; break }
    }
    if (end < 0) { out.push(...lines.slice(i)); break }
    const block = lines.slice(i, end + 1)
    const art = info.toLowerCase() === 'mermaid' ? renderMermaid(lines.slice(i + 1, end).join('\n'), maxWidth) : null
    if (art === null) out.push(...block)
    else {
      const cr = lines[i].endsWith('\r') ? '\r' : ''
      out.push(`${indent}${fence}text${cr}`, `${indent}mermaid → 도해${cr}`, ...art.split('\n').map(l => indent + l + cr), lines[end])
      changed = true
    }
    i = end
  }
  return changed ? out.join('\n') : markdown
}
