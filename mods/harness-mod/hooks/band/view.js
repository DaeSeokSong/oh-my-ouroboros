// 줄(세그먼트 배열) → Box/Text 트리. 색은 팔레트(어두운·밝은)에서 16진 값으로 칠한다. 팔레트 값의 정본: plan 2026-10-16-harness-mod-band-permissions-pastel.md 3절.
// Text 중첩은 확인되지 않아 한 줄을 Text 여러 개의 행 Box 로 만든다(시안 design.md 6절).
// 버튼은 flexGrow 빈 Box 로 오른쪽 끝에 밀고 flexShrink 0 Box 로 감싸 줄어들지 않게 한다.
// 줄이 넘칠 때 줄어드는 것은 «버튼을 뺀 마지막 Text» 뿐이다(flexShrink 1 + truncate-end, 검수 researcher 4).
// model.js 의 clip 이 이미 한도에 맞추므로 이것은 폭 계산 오차(모호 폭 문자 등)를 받는 안전망이다.
// 띠 바탕은 바깥 Box 의 backgroundColor 가 칠하고, Text 에도 같은 바탕을 명시해 Box 바탕이 글자 칸에 상속되지 않는 터미널에서도 얼룩이 없게 한다.
// 배지·바탕 위의 글자색(on)은 두 팔레트 모두 진한 색이다.
// chip(2026-11-03): 버튼 칩의 배경색. 어두운 테마는 바탕보다 밝은 회색, 밝은 테마는 바탕보다 어두운 회색이라 버튼 글자(btn)가 읽힌다.
export const PALETTES = {
  dark: { bg: '#272A3A', fg: '#ECEBF5', label: '#AAA3CC', dim: '#8D8AA6', sep: '#4B4F68', run: '#A9D8FF', ok: '#A8E6C1', ask: '#F6E3A1',
    no: '#FFA8C5', btn: '#FFC4A3', chip: '#3a3a3a', work: '#FFC4A3', srv: '#A9D8FF', noBg: '#FFA8C5', on: '#23202E' },
  light: { bg: '#F2EFFA', fg: '#242132', label: '#7A6FA8', dim: '#8A879C', sep: '#C9C5DA', run: '#2F6FA8', ok: '#2E8A57', ask: '#94740F',
    no: '#C23B6A', btn: '#B5582B', chip: '#dcdcdc', work: '#FFD2B8', srv: '#C2E2FF', noBg: '#FFC2D6', on: '#2A1F2A' },
}

// 톤 이름 → Text 스타일. 모든 Text 가 같은 바탕(p.bg)을 갖고 배지만 제 바탕을 갖는다. 허용 prop 은 color·backgroundColor·bold 뿐.
function tones(p) {
  const t = c => ({ color: c, backgroundColor: p.bg })
  const badge = bg => ({ color: p.on, backgroundColor: bg, bold: true })
  return {
    base: t(p.fg), label: t(p.label), dim: t(p.dim), sep: t(p.sep), run: t(p.run), runBold: { ...t(p.run), bold: true },
    ok: t(p.ok), ask: t(p.ask), warn: t(p.ask), hot: t(p.no), no: { ...t(p.no), bold: true }, self: { ...t(p.fg), bold: true },
    btn: { color: p.btn, backgroundColor: p.chip, bold: true }, workBadge: badge(p.work), srvBadge: badge(p.srv), noBadge: badge(p.noBg),
  }
}

// 한 줄(세그먼트 배열)을 행 Box 로. side 는 key 를 왼쪽(l)·오른쪽(r)·통째(빈 문자열)로 갈라 같은 트리 안 key 가 겹치지 않게 한다.
// 버튼 세그먼트(개정 20): button(줄 끝 버튼, key 로 구분 · spacer 는 버튼 사이 공백), act(세션 줄의 [숨김]·[제거]·[확정]·[취소]·[되돌리기],
// key = band-act-<act>-<sid>). 눌림은 register.js 의 ui.press 훅이 처리하고 onPress 는 비워 둔다(렌더 때의 $ 는 무효일 수 있음).
function rowBox(el, TONE, row, r, side = '') {
  const { Box, Text, Button } = el
  let last = -1
  row.forEach((s, i) => { if (!s.button && !s.act) last = i })
  const firstBtn = row.findIndex(s => s.button)
  return Box({
    key: side + 'row' + r,
    flexDirection: 'row',
    children: row.flatMap((s, i) => s.act
      // s.key: 이름이 band-act- 꼴이 아닌 버튼(Jira 의 band-jira-work-<KEY>)이 제 key 를 직접 지정한다.
      ? [Box({ key: side + 'act' + r + '-' + i, flexShrink: 0, children: [Button({ key: s.key || `band-act-${s.act}-${s.sid}`, label: s.text, plain: true, onPress: () => {},
        children: [Text({ ...TONE.btn, children: [s.text] })] })] })]
      : s.button
      ? [...(i === firstBtn ? [Box({ key: 'band-fill' + r, flexGrow: 1 })] : []),
        Box({ key: 'band-btn' + r + '-' + i, flexShrink: 0, children: [s.spacer ? Text({ ...TONE.base, children: [s.text] })
          : Button({ key: s.key || 'band-toggle', label: s.text.trim(), plain: true, onPress: () => {},
            children: [Text({ ...TONE.btn, children: [s.text] })] })] })]
      // Text 는 공식 요소 표의 prop(color·backgroundColor·bold·dimColor·wrap 등)만 받는다. key·flexShrink 를 Text 에 넣으면
      // 엔진이 띠 전체를 거부하고 자기 그림을 그린다(2026-10-15 실측 «Text prop "flexShrink" is not allowed»).
      // 그래서 배치 prop 은 Text 를 감싸는 Box 가 갖는다.
      : [Box({ key: side + r + '-' + i, flexShrink: i === last ? 1 : 0,
        children: [Text(i === last ? { wrap: 'truncate-end', ...TONE[s.tone], children: [s.text] } : { ...TONE[s.tone], children: [s.text] })] })]),
  })
}

// 토글은 register.js 의 ui.press 훅이 맡는다(렌더 때 붙잡은 $ 는 훅이 끝나면 무효일 수 있음). onPress 는 이중 토글을 막으려 비워 둔다.
// theme: 'dark' | 'light'(그 밖의 값은 dark). split: 지금 그려진 경계의 기본 위치 대비 칸 수(effectiveSplit 값, 끌기 계산용).
// 펼친 보기(모든 줄에 divider 세그먼트가 있음)이고 이 화면에 Client 요소가 있으면(개정 15) 왼쪽 열 · 경계 · 오른쪽 열 세 칸으로 그린다.
// 경계는 surface 모듈 divider.js 가 그리며 포인터를 누르고 끌면 새 split 을 ui.message 로 보낸다. 줄은 model.js 가 이미 왼쪽 폭까지
// 공백으로 채워 두므로 왼쪽 열 폭이 곧 경계 위치다. Client 가 없는 화면은 종전처럼 ` │ ` 글자를 줄 안에 그린다.
// handle(개정 20): 펼친 보기 높이 창 정보({ height, offset, maxOffset, total, auto }). 있으면 맨 위에 높이 조절 줄 하나를 더 그린다.
// Client 가 있는 화면은 height.js(끌기·↑↓·Home·PgUp/PgDn)로, 없는 화면은 글자 한 줄로.
function handleRow(el, p, handle, columns) {
  const { Box, Text } = el
  const scroll = handle.total > 0 && handle.maxOffset > 0 ? ` · 스크롤 ${handle.offset + 1}~${Math.min(handle.total, handle.offset + handle.win)}/${handle.total}` : ''
  // 상한은 이 세션의 지금 최대 높이(엔진 maxRows, 다른 그림 줄 수를 뺀 값). 전체 화면 방식은 엔진이 그 칸을 터미널 절반으로 묶는다(개정 21).
  const now = handle.auto ? '자동' : handle.big ? `최대 ${handle.height}줄` : handle.height + '줄'
  // 개정 23: 상한은 엔진이 띠에 실제로 보여 주는 줄 수다. 전체 화면 방식은 세션 창 절반(프롬프트 포함)에서 할 일 목록 등을 뺀 만큼이다.
  // 개정 24(사용자 지시 «() 안의 내용이 많으니 세션 창의 절반이라고 짧게»): 괄호는 «세션 창의 절반» 만 적는다.
  const cap = `상한 ${handle.cap}줄${handle.fullscreen ? '(세션 창의 절반)' : ''}`
  const label = `높이 ${now} · ${cap}${scroll} · 끌기·↑↓ 높이 · Home 자동 · 휠 넘기기`
  if (el.Client) {
    return el.Client({ key: 'band-height', module: './height.js', width: Math.max(10, columns - 2), height: 1,
      props: { height: handle.height, label, fg: p.dim, active: p.btn, bg: p.bg, line: p.sep } })
  }
  return Box({ key: 'band-height-text', flexDirection: 'row', children: [Text({ color: p.dim, backgroundColor: p.bg, wrap: 'truncate-end', children: [label] })] })
}

// 다른 플러그인·엔진이 띠에 그린 트리(theirs)의 줄 수 어림(qa 2026-10-23): 세로 Box 는 자식 합, 가로 Box 는 자식 최대, Text 는 1 + 줄바꿈 수.
// 펼친 보기는 이만큼을 상한에서 빼야 트리 전체가 maxRows 안에 들어가 엔진이 창을 밀지 않는다(밀면 첫 줄의 접기가 가려진다).
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

// 트리의 Text 글자를 앞에서부터 max 개 모은다(진단용: 띠 자리에 무엇이 그려졌는지 이름을 남긴다). 각 글자는 60자까지.
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
