// 터미널 칸 폭. 한글·한자·전각은 2칸, 그 밖은 1칸.
// 동아시아 폭 «모호» 문자(●○·▸▾)는 1칸으로 센다. 한글 터미널에서 2칸으로 그려질 수 있어
// 줄 한도를 bodyColumns - 2 로 잡아 흡수한다(시안 design.md 2절).
function isWide(c) {
  return (c >= 0x1100 && c <= 0x115f) || (c >= 0x2e80 && c <= 0xa4cf) || (c >= 0xac00 && c <= 0xd7a3) ||
    (c >= 0xf900 && c <= 0xfaff) || (c >= 0xfe30 && c <= 0xfe4f) || (c >= 0xff00 && c <= 0xff60) ||
    (c >= 0xffe0 && c <= 0xffe6) || (c >= 0x1f300 && c <= 0x1faff) || (c >= 0x20000 && c <= 0x3fffd)
}

export function cellWidth(s) {
  let w = 0
  for (const ch of s) w += isWide(ch.codePointAt(0)) ? 2 : 1
  return w
}

export function lineWidth(segs) {
  return segs.reduce((a, s) => a + cellWidth(s.text), 0)
}

// clip: 세그먼트를 앞에서부터 담다가 넘치는 세그먼트를 셀 폭 기준으로 자르고 끝에 «…» 를 붙인다(폭 ≤ limit 보장).
// 넘치지 않으면 row 를 그대로 돌려준다. 순수 함수.
export function clip(row, limit) {
  if (limit < 1) return []
  if (lineWidth(row) <= limit) return row
  const room = limit - 1 // «…» 1칸 확보
  const out = []
  let used = 0
  for (const s of row) {
    const w = cellWidth(s.text)
    if (used + w <= room) { out.push(s); used += w; continue }
    let text = ''
    for (const ch of s.text) {
      const cw = cellWidth(ch)
      if (used + cw > room) break
      text += ch
      used += cw
    }
    out.push({ ...s, text: text + '…' })
    break
  }
  return out
}

// splitAt: 앞에서부터 셀 폭 limit 칸까지를 head, 나머지를 rest 로 가른다(세그먼트 tone 유지, 한 세그먼트가 걸치면 둘로 쪼갠다). 순수 함수.
export function splitAt(row, limit) {
  const head = [], rest = []
  let used = 0, full = false
  for (const s of row) {
    if (full) { rest.push(s); continue }
    const w = cellWidth(s.text)
    if (used + w <= limit) { head.push(s); used += w; continue }
    let a = '', b = ''
    for (const ch of s.text) {
      const cw = cellWidth(ch)
      if (!b && used + cw <= limit) { a += ch; used += cw } else b += ch
    }
    if (a) head.push({ ...s, text: a })
    rest.push({ ...s, text: b })
    full = true
  }
  return [head, rest]
}
