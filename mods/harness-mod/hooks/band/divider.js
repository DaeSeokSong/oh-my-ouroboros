// 띠 펼친 보기의 좌우 경계(개정 15, surface 모듈: 그리는 쪽에서 돌고 $ 가 없다. 플러그인과는 post 로만 말한다).
// 끌기: 왼쪽 버튼을 누른 순간 경계의 «절대 열»(영역 안 x + 그때 offset)과 그때 offset 을 기억한다. 영역은 offset 만큼 옮겨 그려지므로
//   지금 절대 열 = e.x + props.offset 이고, 새 offset = 시작 offset + (지금 절대 열 − 시작 절대 열) 이다. 값이 바뀔 때만 { split } 을 보낸다.
//   누른 뒤에는 영역 밖으로 나가도 move 가 계속 온다(엔진의 포인터 붙잡기). 끝 위치는 플러그인이 effectiveSplit 으로 잘라 저장한다.
// 키: 경계를 한 번 누르면 키 입력을 받는다. ←/→ 는 2칸씩 옮기고(tmux 처럼 마우스가 안 넘어오는 터미널용), Esc 는 엔진이 프롬프트로 돌려준다.
// setState 는 포인터 이벤트에서만 부른다(이벤트 없이 연속 setState 하면 엔진이 그리기 반복으로 보고 내린다).
export default function BandDivider(props, surface) {
  const { Box, Text } = surface.elements
  const p = props && typeof props === 'object' ? props : {}
  const off = typeof p.offset === 'number' && Number.isFinite(p.offset) ? p.offset : 0
  const rows = Math.max(1, Math.min(200, Number.isInteger(p.rows) ? p.rows : 1))
  surface.onPointer(e => {
    const s = surface.state
    if (e.type === 'down' && e.button === 'left') {
      surface.setState({ start: e.x + off, base: off, sent: off })
    } else if (e.type === 'move' && s && typeof s.start === 'number' && e.button === 'left') {
      const next = s.base + (e.x + off - s.start)
      if (next !== s.sent) {
        surface.post({ split: next })
        surface.setState({ ...s, sent: next })
      }
    } else if (e.type === 'up' && s && typeof s.start === 'number') {
      surface.setState({})
    }
  })
  surface.onKey(k => {
    if (k.key === 'left') surface.post({ nudge: -2 })
    else if (k.key === 'right') surface.post({ nudge: 2 })
  })
  const dragging = !!(surface.state && typeof surface.state.start === 'number')
  const color = dragging ? p.active : p.fg
  return Box({
    flexDirection: 'column',
    children: Array.from({ length: rows }, () => Text({ color, backgroundColor: p.bg, bold: dragging, children: [' │ '] })),
  })
}
