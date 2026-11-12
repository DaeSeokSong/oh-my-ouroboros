// harness-mod 가 $.state 에 두는 값의 계약. 세션 단위(리로드에도 유지)이고 테마 종류만 담는다.
export type HarnessModTheme = 'dark' | 'light'

declare module 'claude-code' {
  interface PluginState {
    'harness-mod': {
      theme: HarnessModTheme; split: number; propStart: number
      // 개정 20: 펼친 보기 높이(0 = 자동, 세션을 넘어서는 $.store 'band-height'), 넘김 위치(세션 안), 숨긴 세션 sid(모든 세션 공통 $.store 'band-hidden' 의 사본)
      height: number; scroll: number; hidden: string[]
      // 개정 27: 화면 마스킹 켬/끔(기본 true, 세션을 넘어서는 $.store 'band-mask' 의 사본). 화면 표시 전용이며 모델·기록의 원문은 바뀌지 않는다.
      mask: boolean
      // 2026-11-02: 이 세션의 뉴스 줄 보기(max 크게 · min 작게 · off 끔). 정본은 ~/.claudenews/view.<세션 id> 파일이고 이것은 버튼 글자용 사본이다.
      news: 'max' | 'min' | 'off'
      // 2026-11-02: 이 mod 의 알림이 아닌 첫 지시를 본 뒤 true. false 인 빈 세션에는 하네스 전파 알림을 넣지 않는다.
      awake: boolean
      // 2026-11-03: 이 세션의 모바일 모드(켬 true). 정본은 decision-popup 이 쓰는 ~/.claude/_usage/decision-popup/mobile/<세션 id> 파일이고 이것은 «📱 모바일» 버튼 글자용 사본이다.
      mobile: boolean
    }
  }
}
