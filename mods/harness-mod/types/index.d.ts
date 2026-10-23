// harness-mod 가 $.state 에 두는 값의 계약. 세션 단위(리로드에도 유지)이고 테마 종류만 담는다.
export type HarnessModTheme = 'dark' | 'light'

declare module 'claude-code' {
  interface PluginState {
    'harness-mod': {
      theme: HarnessModTheme; split: number; propStart: number
      // 개정 20: 펼친 보기 높이(0 = 자동, 세션을 넘어서는 $.store 'band-height'), 넘김 위치(세션 안), 숨긴 세션 sid(모든 세션 공통 $.store 'band-hidden' 의 사본)
      height: number; scroll: number; hidden: string[]
      // 개정 27: 화면 가림 켬/끔(기본 true, 세션을 넘어서는 $.store 'band-mask' 의 사본). 화면 표시 전용이며 모델·기록의 원문은 바뀌지 않는다.
      mask: boolean
    }
  }
}
