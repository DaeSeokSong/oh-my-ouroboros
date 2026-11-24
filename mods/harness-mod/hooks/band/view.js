// 줄(세그먼트 배열) → Box/Text 트리. 색은 팔레트(어두운·밝은)에서 16진 값으로 칠한다. 팔레트 값의 정본: plan 2026-10-16-harness-mod-band-permissions-pastel.md 3절.
// REF: knowledge/harness/code-history/mods__harness-mod__hooks__band__view.js.md
export const PALETTES = {
  dark: { bg: '#272A3A', fg: '#ECEBF5', label: '#AAA3CC', dim: '#8D8AA6', sep: '#4B4F68', run: '#A9D8FF', ok: '#A8E6C1', ask: '#F6E3A1',
    no: '#FFA8C5', btn: '#FFC4A3', chip: '#3a3a3a', work: '#FFC4A3', srv: '#A9D8FF', noBg: '#FFA8C5', on: '#23202E', loginY: '#FFE066', loginO: '#FFA033', loginR: '#FF5C5C' },
  light: { bg: '#F2EFFA', fg: '#242132', label: '#7A6FA8', dim: '#8A879C', sep: '#C9C5DA', run: '#2F6FA8', ok: '#2E8A57', ask: '#94740F',
    no: '#C23B6A', btn: '#B5582B', chip: '#dcdcdc', work: '#FFD2B8', srv: '#C2E2FF', noBg: '#FFC2D6', on: '#2A1F2A', loginY: '#8A6A00', loginO: '#B85300', loginR: '#C4122F' },
}

function tones(p) {
  const t = c => ({ color: c, backgroundColor: p.bg })
  const badge = bg => ({ color: p.on, backgroundColor: bg, bold: true })
  return {
    base: t(p.fg), label: t(p.label), dim: t(p.dim), sep: t(p.sep), run: t(p.run), runBold: { ...t(p.run), bold: true },
    ok: t(p.ok), ask: t(p.ask), warn: t(p.ask), hot: t(p.no), no: { ...t(p.no), bold: true }, self: { ...t(p.fg), bold: true },
    btn: { color: p.btn, backgroundColor: p.chip, bold: true }, workBadge: badge(p.work), srvBadge: badge(p.srv), noBadge: badge(p.noBg),
    loginY: { ...t(p.loginY), bold: true }, loginO: { ...t(p.loginO), bold: true }, loginR: { ...t(p.loginR), bold: true },
  }
}

// NEVER: onPress 에 동작을 넣지 않는다. 눌림은 register.js 의 ui.press 훅이 처리한다(렌더 때 붙잡은 $ 는 훅이 끝나면 무효일 수 있고, 비워 두어 이중 토글을 막는다).
function rowBox(el, TONE, row, r, side = '') {
  const { Box, Text, Button } = el
  let last = -1
  row.forEach((s, i) => { if (!s.button && !s.act) last = i })
  const firstBtn = row.findIndex(s => s.button)
  return Box({
    key: side + 'row' + r,
    flexDirection: 'row',
    children: row.flatMap((s, i) => s.act
      ? [Box({ key: side + 'act' + r + '-' + i, flexShrink: 0, children: [Button({ key: s.key || `band-act-${s.act}-${s.sid}`, label: s.text, plain: true, onPress: () => {},
        children: [Text({ ...TONE.btn, children: [s.text] })] })] })]
      : s.button
      ? [...(i === firstBtn ? [Box({ key: 'band-fill' + r, flexGrow: 1 })] : []),
        Box({ key: 'band-btn' + r + '-' + i, flexShrink: 0, children: [s.spacer ? Text({ ...TONE.base, children: [s.text] })
          : Button({ key: s.key || 'band-toggle', label: s.text.trim(), plain: true, onPress: () => {},
            children: [Text({ ...TONE.btn, children: [s.text] })] })] })]
      // NEVER: Text 에 key·flexShrink 를 넣지 않는다. Text 는 공식 요소 표의 prop(color·backgroundColor·bold·dimColor·wrap 등)만 받고, 어기면 엔진이 띠 전체를 거부하고 자기 그림을 그린다(2026-10-15 실측 «Text prop "flexShrink" is not allowed»). 배치 prop 은 Text 를 감싸는 Box 가 갖는다.
      : [Box({ key: side + r + '-' + i, flexShrink: i === last ? 1 : 0,
        children: [Text(i === last ? { wrap: 'truncate-end', ...TONE[s.tone], children: [s.text] } : { ...TONE[s.tone], children: [s.text] })] })]),
  })
}

function handleRow(el, p, handle, columns) {
  const { Box, Text } = el
  const scroll = handle.total > 0 && handle.maxOffset > 0 ? ` · 스크롤 ${handle.offset + 1}~${Math.min(handle.total, handle.offset + handle.win)}/${handle.total}` : ''
  const now = handle.auto ? '자동' : handle.big ? `최대 ${handle.height}줄` : handle.height + '줄'
  const cap = `상한 ${handle.cap}줄${handle.fullscreen ? '(세션 창의 절반)' : ''}`
  const label = `높이 ${now} · ${cap}${scroll} · 끌기·↑↓ 높이 · Home 자동 · 휠 넘기기`
  if (el.Client) {
    return el.Client({ key: 'band-height', module: './height.js', width: Math.max(10, columns - 2), height: 1,
      props: { height: handle.height, label, fg: p.dim, active: p.btn, bg: p.bg, line: p.sep } })
  }
  return Box({ key: 'band-height-text', flexDirection: 'row', children: [Text({ color: p.dim, backgroundColor: p.bg, wrap: 'truncate-end', children: [label] })] })
}

export function treeRows(node, depth = 0) {
  if (!node || typeof node !== 'object' || depth > 40) return 0
  if (Array.isArray(node)) return node.reduce((a, c) => a + treeRows(c, depth + 1), 0)
  const kids = Array.isArray(node.children) ? node.children : node.props && Array.isArray(node.props.children) ? node.props.children : []
  const type = node.type || node.t
  if (type === 'Text') {
    const s = kids.filter(c => typeof c === 'string').join('')
    return 1 + (s.match(/\n/g) || []).length
  }
  const dir = node.flexDirection || (node.props && node.props.flexDirection)
  const parts = kids.map(c => (typeof c === 'string' ? 1 : treeRows(c, depth + 1)))
  if (!parts.length) return type === 'Box' ? 0 : 1
  return dir === 'row' ? Math.max(...parts) : parts.reduce((a, b) => a + b, 0)
}

export function treeTexts(node, max = 6, out = [], depth = 0) {
  if (!node || typeof node !== 'object' || depth > 40 || out.length >= max) return out
  if (Array.isArray(node)) { node.forEach(c => treeTexts(c, max, out, depth + 1)); return out }
  const kids = Array.isArray(node.children) ? node.children : node.props && Array.isArray(node.props.children) ? node.props.children : []
  for (const c of kids) {
    if (out.length >= max) break
    if (typeof c === 'string') { if (c.trim()) out.push(c.slice(0, 60)) } else treeTexts(c, max, out, depth + 1)
  }
  return out
}

export function toTree(el, rows, theme = 'dark', split = 0, handle = null, columns = 80) {
  const { Box } = el
  const p = Object.prototype.hasOwnProperty.call(PALETTES, theme) ? PALETTES[theme] : PALETTES.dark
  const tree = bodyTree(el, rows, p, split)
  if (!handle || handle.handle === false) return tree
  return Box({ flexDirection: 'column', backgroundColor: p.bg, children: [handleRow(el, p, handle, columns), tree] })
}

function bodyTree(el, rows, p, split) {
  const { Box } = el
  const TONE = tones(p)
  const cut = rows.map(row => row.findIndex(s => s.divider))
  if (el.Client && rows.length && cut.every(i => i >= 0)) {
    return Box({
      key: 'band-body', flexDirection: 'row', backgroundColor: p.bg, paddingX: 1,
      children: [
        Box({ key: 'band-left', flexDirection: 'column', flexShrink: 0, children: rows.map((row, r) => rowBox(el, TONE, row.slice(0, cut[r]), r, 'l')) }),
        el.Client({ key: 'band-divider', module: './divider.js', width: 3, height: rows.length,
          props: { rows: rows.length, offset: split, fg: p.sep, active: p.btn, bg: p.bg } }),
        Box({ key: 'band-right', flexDirection: 'column', flexGrow: 1, children: rows.map((row, r) => rowBox(el, TONE, row.slice(cut[r] + 1), r, 'r')) }),
      ],
    })
  }
  return Box({
    key: 'band-body', flexDirection: 'column', backgroundColor: p.bg, paddingX: 1,
    children: rows.map((row, r) => rowBox(el, TONE, row.map(s => (s.divider ? { text: s.text, tone: s.tone } : s)), r)),
  })
}
