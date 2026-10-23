// 띠 펼친 보기의 높이 조절 줄(개정 20, surface 모듈: 그리는 쪽에서 돌고 $ 가 없다. 플러그인과는 post 로만 말한다).
// 사용자 지시(2026-10-23): «상태창 자체의 세로폭을 조절할 수 있도록 해서 해당 세션 전체를 덮거나 반을 덮거나».
// 띠는 프롬프트 바로 위에 붙어 있어 아래 끝이 고정이고, 이 줄은 띠의 맨 위다. 그래서 위로 끌면 높이가 는다.
// 끌기: 왼쪽 버튼을 누른 순간 «띠 아래 끝 기준 절대 행»(e.y − 그때 높이)과 그때 높이를 기억한다. 높이가 바뀌면 이 줄도 같이 움직이므로
//   지금 절대 행 = e.y − props.height 이고, 새 높이 = 시작 높이 + (시작 절대 행 − 지금 절대 행) 이다. 값이 바뀔 때만 { height } 를 보낸다.
//   끝 높이는 플러그인이 엔진 상한(maxRows)에 맞춰 잘라 저장한다.
// 키: 이 줄을 한 번 누르면 키 입력을 받는다. ↑/↓ 는 높이 ±2줄, Home 은 자동 높이, PgUp/PgDn 은 내용 넘기기(휠이 안 오는 터미널용).
// setState 는 포인터 이벤트에서만 부른다(divider.js 와 같은 까닭).
export default function BandHeight(props, surface) {
  const { Box, Text } = surface.elements
  const p = props && typeof props === 'object' ? props : {}
  const h = typeof p.height === 'number' && Number.isFinite(p.height) ? p.height : 0
  surface.onPointer(e => {
    const s = surface.state
    if (e.type === 'down' && e.button === 'left') {
      surface.setState({ start: e.y - h, base: h, sent: h })
    } else if (e.type === 'move' && s && typeof s.start === 'number' && e.button === 'left') {
      const next = s.base + (s.start - (e.y - h))
      if (next !== s.sent) {
        surface.post({ height: next })
        surface.setState({ ...s, sent: next })
      }
    } else if (e.type === 'up' && s && typeof s.start === 'number') {
      surface.setState({})
    }
  })
  surface.onKey(k => {
    if (k.key === 'up') surface.post({ nudge: 2 })
    else if (k.key === 'down') surface.post({ nudge: -2 })
    else if (k.key === 'home') surface.post({ auto: true })
    else if (k.key === 'pageup') surface.post({ scroll: -1 })
    else if (k.key === 'pagedown') surface.post({ scroll: 1 })
  })
  const dragging = !!(surface.state && typeof surface.state.start === 'number')
  return Box({
    flexDirection: 'row',
    children: [Text({ color: dragging ? p.active : p.line, backgroundColor: p.bg, bold: dragging, children: ['━━ '] }),
      Text({ color: dragging ? p.active : p.fg, backgroundColor: p.bg, wrap: 'truncate-end', children: [String(p.label || '')] })],
  })
}
