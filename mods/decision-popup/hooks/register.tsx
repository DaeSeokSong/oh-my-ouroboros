import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import type { DecisionExperiment, DecisionItem, DecisionRequest } from '../types'

// 결정 팝업: 모델이 결정 항목을 넘기면 대화창처럼 포커스를 잡는 pane 을 연다.
// 항목마다 한 페이지, 숫자키로 고르면 다음 항목으로 넘어가고, 마지막 요약 페이지에서
// «확인»을 누르면 고른 값이 이 세션에 새 메시지로 들어간다(확인 전에는 아무것도 보내지 않는다).
// 확정하지 않고 닫으면 «확정하지 않고 닫음»만 알린다.
// 항목 페이지 차례(개정 21, intent/2026-10-28-popup-terms-paragraphs-scenario.md 개정 2): 제목 → 문제(문단마다 한 줄) → 번호 선택지
// → «직접 입력» 칸 → 장단점 표 → «용어» 표(용어 | 설명, terms 있을 때) → 실험 정리 표(experiments 있을 때)
// → «예시(문제)»(scenario, 필수) 와 그 아래 들여 쓴 «선택지별 예시»(항상) → 이동 줄. 세 표는 머리 아래와 행 사이마다 가로 구분선(2026-10-28 사용자 지시).
//
// 그릴 주체 사전 차단(intent/2026-10-28-designer-backend-popup-gate.md): 처음에는 main 이 Agent · Task 도구로 subagent_type=designer 를 부르려 할 때,
// 사용자의 마지막 글(사람 글) 뒤에 결정 팝업 답(«[결정 팝업 확인]» 전송)이 없으면 거부하고 그릴 주체를 팝업으로 먼저 묻게 했다(대상은 아래 «대상 이동»).
// 근거: 사용자 원문(2026-10-28) «하네스에게 분명 "이미지 요청이 있다면 designer가 그릴지 아니면 연결된 다른 에이전트에게 요청할지 물어보도록"
// 이런 말을 했었는데 지금 호출이 안 됐네? 피드백 발동시켜». 질문 표가 agents/designer.md 안에만 있어 main 이 호출 전에 읽지 못한 실사고라 규칙 문구가 아닌 도구 차단으로 막는다.
// 결정 D1(호출 전 차단, 팝업 답 근거) · D2(모든 그림 요청). 받아들인 틈: 팝업 답의 주제는 가리지 않는다(어떤 팝업 답이든 통과, 기계로 주제 대조 불가).
// 대상 이동(2026-11-10 사용자 결정, intent/2026-11-05-agent-consolidation.md 7단계 · 개정 3): designer 에이전트를 figure 스킬로 접어,
// main 이 Skill 도구로 figure 스킬을 부를 때 같은 조건으로 막게 했다. 사용자 원문 «추후 그림 그리는 선택지에는 새로 생성될 그리는 스킬과 코덱스 그록으로 그리는 안이 뜨도록 해».
// 대상 확대(2026-11-10 사용자 결정): 1) 그림 · 시각화 스킬 호출 2) Artifact 페이지 게시 3) 그림 스크립트 · 시각화 산출물(.html · .htm · .svg) Write · Edit
// 4) Bash 의 그림 스크립트 실행. 예외 C: Confluence 저장 형식 html(VISUAL_EXEMPT). D: 서브에이전트 호출에도 건다(근거 상태는 세션 단위).
// 사용자 원문 «3으로 하고 html 같은 시각화 무언가를 만들 때 항상 걸리도록 해», «3으로 하고 미리 사용자에게 허가 받고 서브에이전트 호출하도록 진행하여 메인으로 돌아오는 과정 없애».
// 남는 틈: 대상 꼴(FIGURE_SCRIPT · VISUAL_OUTPUT · DRAWING_SKILLS)에 안 걸리는 이름 · 경로로 만드는 산출물과 Bash 리다이렉션으로 쓰는 파일,
// 사용자가 /figure 를 직접 입력하는 길은 걸리지 않는다. 후속 수정에도 사람 글마다 질문이 다시 뜨는 것은 사용자가 고른 동작이다.
// 검수(2026-11-10)로 더 적는 틈: Bash 리다이렉션이나 스크립트 안에서 만드는 산출물, runsFigureScript 판정 꼴에 안 드는 실행 방식은 걸리지 않고,
// 반대로 그림이 아닌 html · svg 소스(웹 자산 · 템플릿) 편집에도 질문이 뜨는 오탐이 있다. Bash 판정은 따옴표를 모르므로
// 따옴표 안 구분자로 과차단하고(git commit -m "x; python gen_x_plt.py") bash -c "…" 안의 실행은 놓친다.
// 닫힘(«[결정 팝업 닫힘]») 은 답이 아니다. 기억은 참 · 거짓 하나만 두고 글은 저장하지 않는다.
//
// 모바일 모드(intent/2026-10-29-mobile-choice-mode.md): 사용자가 해제할 때까지 설명은 채팅 글, 선택은 AskUserQuestion, 결정 팝업은 쓰지 않는다.
// 근거: 사용자 원문(2026-10-29, 한 학습 세션) «당분간 모바일 클로드 앱으로 작업할 거니까 ... 팝업 말고 내가 말할 때까지 선택지로 제공해» →
// «사용자가 선택지를 클릭 또는 터치해서 선택할 수 있게 ... 설명은 텍스트로 띄우고 선택지를 그렇게 선택할 수 있도록 하란 거야» → «모바일, 선택지 띄워».
// 켜고 끄는 방식(2026-11-10 사용자 결정 «모바일 모드에 대해서는 명령어로만 껐다 켤 수 있게 해»): `/mobile-mode [on|off|켜기|끄기]` 명령(띠의 📱 버튼이 부르는 길)만 상태를 바꾼다. 사람 글로는 바뀌지 않는다.
// 실사고 2건(2026-11-10): «지금 모바일 모드 off인 상태야 다시 팝업으로 물어봐» 라는 글에 «모바일» 이 있다고 모드가 다시 켜졌고,
// 서버 재부팅 뒤 세션이 다시 뜨면 상태(atom 기본값 false)가 꺼짐으로 초기화돼 켜 둔 사용자의 상태와 어긋났다. 그래서 세션 시작 때 상태 파일이 on 이면 상태를 되살린다.
// 상태는 참 · 거짓 하나뿐이다. 사람 글에서 «모바일·안 보임» 을 읽는 판정(hiddenFromPrompt · 이번 회차 AskUserQuestion 예외)은 모드와 별개라 그대로다.
// `/mobile-mode` 명령(2026-11-03, intent/2026-11-03-band-button-chips-mobile-toggle.md)은 하네스 띠의 «📱 모바일» 버튼이 부르는 길이다.
// 이름이 `/mobile` 이 아닌 까닭: `/mobile` 은 Claude Code 가 내장한 명령이라 $.command.register 가 거부하고 훅이 건너뛰어진다(claude plugin validate 가 알려 줌). 상태가 바뀔 때마다
// <HOME>/.claude/_usage/decision-popup/mobile/<세션 id> 에 on / off 를 써서 띠가 버튼 글자를 정한다. 판정(팝업 거부 · AskUserQuestion 허용)은 그대로다.

const PLUGIN = 'decision-popup'
const PANE = 'decision'
const TOOL = 'ask'

const REQUEST_REF = { plugin: 'decision-popup', key: 'request' } as const
const request = atom(REQUEST_REF, null as DecisionRequest | null)
const answers = atom({ plugin: 'decision-popup', key: 'answers' } as const, {} as Record<string, number>)
// 주관식 칸(개정 17, 2026-10-21 사용자 지시): 항목마다 «직접 입력» 칸 하나. 그 답은 answers 에 FREE(-1)로 표시하고 글은 texts 에 둔다.
// 번호 선택지를 다시 고르면 texts 에서 지운다(답은 항목마다 하나).
const texts = atom({ plugin: 'decision-popup', key: 'texts' } as const, {} as Record<string, string>)
const page = atom({ plugin: 'decision-popup', key: 'page' } as const, 0)
const FREE = -1
// 열린 팝업에 새 항목을 붙인 뒤 허용하는 항목 수(한 호출 상한 9의 두 배).
const MAX_ITEMS = 18
const TITLE_MAX = 120 // 이어 붙인 팝업 제목의 최대 글자 수

// AskUserQuestion 사전 차단(intent/2026-10-27-askuserquestion-popup-gate.md)이 쓰는 기억 값 둘.
// 모듈 변수가 아니라 세션 상태에 둔다: 모듈이 다시 적재돼도 판정이 이어지고, 시험마다 값이 섞이지 않는다.
// 글 전체가 아니라 판정 결과(bool)만 담는다: 세션 상태는 다른 플러그인도 읽으므로 붙여 넣은 비밀값이 새지 않게(2026-10-27 security 낮음).
const userSaidHidden = atom({ plugin: 'decision-popup', key: 'userSaidHidden' } as const, false)
const unplaced = atom({ plugin: 'decision-popup', key: 'unplaced' } as const, false)
// 원문자 자동 치환 때 이 세션에서 적은 T41 줄 수(상한 T41_CAP).
const t41Logged = atom({ plugin: 'decision-popup', key: 't41Logged' } as const, 0)
// 사용자의 마지막 사람 글 뒤에 결정 팝업 답(확인 전송)이 있었는가. 사람 글이 오면 false, 확인 전송 직후 true.
const answeredSinceHuman = atom({ plugin: 'decision-popup', key: 'answeredSinceHuman' } as const, false)
const T41_CAP = 5
// 팝업이 스스로 넣는 글은 사용자 메시지가 아니다(기억을 덮어쓰지 않는다).
const OWN_MESSAGE = /^\s*\[결정 팝업 (?:확인|닫힘)\]/
// 이번 회차에 모바일·팝업 안 보임을 말한 표현(놓친 표현이 나오면 더한다).
// «안 보내»·«팝업 안에» 같은 일반 문장에 걸리지 않게 «안 보여/보임/보이» · «안 떠/뜨» 꼴만 받는다(2026-10-27 main 검수).
const MOBILE_OR_HIDDEN = /모바일|핸드폰|휴대폰|폰으로|안\s*보[여이임]|안\s*(?:떠|뜨)|팝업이\s*안/
const PUBLISH_APPROVAL = /게시\s*승인/
// 모바일 모드: `/mobile-mode` 명령으로 해제할 때까지 유효한 세션 상태(참 · 거짓만).
const mobileMode = atom({ plugin: 'decision-popup', key: 'mobileMode' } as const, false)

// prompt.submit 한 건을 «모바일·안 보임 판정» 으로 바꾼다. 사람이 쓴 글(composer · bridge)이 아니거나 이 mod 가 넣은 글이면 null(기억을 건드리지 않음).
// 시험 도구는 prompt.submit 출처를 사람으로 꾸밀 수 없어서 판정을 순수 함수로 떼어 직접 시험한다.
export function hiddenFromPrompt(kind: string | undefined, text: string): boolean | null {
  if (!isHumanPrompt(kind, text)) return null

  return MOBILE_OR_HIDDEN.test(text)
}

// `/mobile-mode` 인자 → 새 상태(2026-11-03, intent/2026-11-03-band-button-chips-mobile-toggle.md): on · 켜기 → true, off · 끄기 → false, 없거나 그 밖이면 지금 값을 뒤집는다.
// 영어는 대소문자 무관, 키는 자기 것만 본다(«constructor» 같은 프로토타입 이름이 값으로 풀리지 않게).
const MOBILE_ARG: Record<string, boolean> = { on: true, 켜기: true, off: false, 끄기: false }
export function mobileModeFromArg(args: string, current: boolean): boolean {
  const arg = args.trim().toLowerCase()

  return Object.prototype.hasOwnProperty.call(MOBILE_ARG, arg) ? MOBILE_ARG[arg] : !current
}

// 모바일 상태 파일: 상태가 바뀔 때마다 <HOME>/.claude/_usage/decision-popup/mobile/<세션 id> 에 on / off 한 줄을 쓴다. 하네스 띠의 «📱 모바일» 버튼 글자가 이 파일을 읽는다.
// 세션 id 는 파일 이름이라 모양을 검사하고, HOME 은 절대 경로일 때만 쓴다. 실패해도 모드 전환은 막지 않는다.
const SESSION_ID_OK = /^[A-Za-z0-9_-]{1,64}$/
type MobileFileApi = {
  env: { get(key: string): Promise<unknown> }
  session: { id(): Promise<unknown> }
  fs: { write(path: string, text: string): Promise<unknown>; read(path: string): Promise<unknown> }
}
async function mobileFilePath($: MobileFileApi): Promise<string | null> {
  const home = String((await $.env.get('HOME')) || '')
  const sid = String(await $.session.id())

  return home.startsWith('/') && home !== '/' && SESSION_ID_OK.test(sid) ? `${home}/.claude/_usage/decision-popup/mobile/${sid}` : null
}
async function writeMobileFile($: MobileFileApi, on: boolean): Promise<void> {
  try {
    const path = await mobileFilePath($)
    if (path) await $.fs.write(path, on ? 'on\n' : 'off\n')
  } catch {
    // 상태 파일을 못 써도 모드는 그대로 바뀐다(띠 버튼 글자만 늦는다)
  }
}
// 세션 시작 때 상태 파일을 읽는다: 내용이 on 이면 true, 파일이 없거나 읽기에 실패하면 false(재시작 때 명령으로 정한 값을 잃지 않게).
async function readMobileFile($: MobileFileApi): Promise<boolean> {
  try {
    const path = await mobileFilePath($)

    return path ? String(await $.fs.read(path)).trim() === 'on' : false
  } catch {
    return false
  }
}

// «잘못된 막힘» 표시 파일(2026-11-11, intent/2026-11-11-plan-confirm-gate.md 성공 기준 10의 4 · 계획 2.5): 사용자가 고른 선택지 이름이 WRONG_BLOCK_LABEL 과
// 정확히 같을 때만(결정 팝업 확정 · AskUserQuestion 답 모두) <HOME>/.claude/_usage/plan-confirm-gate/wrong-block/<세션 id> 를 쓴다. 직접 입력 글로는 생기지 않는다.
// 접두 일치가 아니라 정확한 일치인 까닭(2026-11-11 검수): «잘못된 막힘 아님» 같은 다른 뜻의 이름까지 표시를 만들면 안 된다.
// 왜 대화 기록과 따로 두나: 계획 확정 훅(scripts/plan-confirm-gate.py)이 고장 나 판정하지 못하면 대화 기록도 못 읽는 상태일 수 있어, 훅을 고치는 수정까지
// 막히지 않게 별도 표시로 전한다. 훅은 판정 불가일 때만 이 표시를 보고 훅 자신의 파일 묶음 Write · Edit 만 통과시킨다(시간으로 풀리는 통과 없음).
// 이름은 config/plan-confirm-gate.json 의 wrong_block_label 과 같아야 한다(scripts/tests/test_plan_confirm_gate.py 가 대조). 쓰기가 실패해도 확정 · 답 전달은 그대로다.
const WRONG_BLOCK_LABEL = '잘못된 막힘'
async function writeWrongBlockMarker($: MobileFileApi): Promise<void> {
  try {
    const home = String((await $.env.get('HOME')) || '')
    const sid = String(await $.session.id())
    if (home.startsWith('/') && home !== '/' && SESSION_ID_OK.test(sid)) {
      await $.fs.write(`${home}/.claude/_usage/plan-confirm-gate/wrong-block/${sid}`, `${new Date().toISOString()}\n`)
    }
  } catch {
    // 표시를 못 써도 확정 · 답 전달은 막지 않는다(훅은 계속 판정 불가로 막고, 사용자는 다시 고를 수 있다)
  }
}
// 팝업 한 항목에서 번호 선택지(직접 입력 아님)를 골랐고 그 이름이 «잘못된 막힘» 과 정확히 같은가
function pickedWrongBlock(it: DecisionItem, k: number | undefined): boolean {
  return k !== undefined && k !== FREE && it.options[k]?.label === WRONG_BLOCK_LABEL
}
// AskUserQuestion 결과에서 고른 선택지 이름이 «잘못된 막힘» 과 정확히 같은가. 답이 그 질문의 선택지 이름과 같을 때만 고른 것으로 친다
// (선택지 밖의 글 = 사용자가 직접 친 글, afkTimeoutMs = 사람이 아닌 자동 응답은 제외). 여럿 고르기 답은 «, » 로 이어진 이름들이다.
export function askPickedWrongBlock(result: unknown): boolean {
  const r = result as { questions?: unknown; answers?: unknown; afkTimeoutMs?: unknown } | null
  if (!r || typeof r !== 'object' || r.afkTimeoutMs !== undefined || !Array.isArray(r.questions) || !r.answers || typeof r.answers !== 'object') return false
  const answers = r.answers as Record<string, unknown>

  return r.questions.some(q => {
    const qq = q as { question?: unknown; options?: unknown; multiSelect?: unknown } | null
    if (typeof qq?.question !== 'string' || !Array.isArray(qq.options) || !Object.prototype.hasOwnProperty.call(answers, qq.question)) return false
    const labels = qq.options.map(o => (o as { label?: unknown } | null)?.label).filter((l): l is string => typeof l === 'string')
    const a = answers[qq.question]
    if (typeof a !== 'string') return false
    const parts = labels.includes(a) ? [a] : qq.multiSelect === true ? a.split(', ') : []

    return parts.length > 0 && parts.every(p => labels.includes(p)) && parts.some(p => p === WRONG_BLOCK_LABEL)
  })
}

// 사람이 쓴 글인가: 출처가 composer · bridge 이고 이 mod 가 넣은 글이 아니다. 피어 세션·작업 알림·플러그인 글은 사람 글이 아니다.
export function isHumanPrompt(kind: string | undefined, text: string): boolean {
  return (kind === 'composer' || kind === 'bridge') && !OWN_MESSAGE.test(text)
}

// 그릴 주체 팝업 답이 있어야 부를 수 있는 스킬. drawio-skill 은 figure 스킬의 그리기 수단이고 접기 전에는 designer 를 거쳐야 했으므로
// 직접 부르는 길도 같은 조건으로 막는다(2026-11-10 검수). dataviz · artifact-design · artifact-diagramming 은 html · 차트 · 도해를 만드는 스킬이다(2026-11-10 사용자 결정).
const DRAWING_SKILLS = ['figure', 'drawio-skill', 'dataviz', 'artifact-design', 'artifact-diagramming']
// 그림 스크립트 꼴: figure 스킬 § 저장 표준의 이름(figures 폴더 아래 gen_{name}.py · gen_{name}_tikz.py)에 더해 실제 산출물에서 쓰는 관행인
// _plt 접미(gen_{name}_plt.py)를 함께 받는다. _tikz · _plt 접미는 figures 폴더 밖에서도 그림 스크립트로 보고, .tikz · .drawio 는 그림 원본이다.
// figures 폴더 밖의 다른 gen_*.py(예: 데이터 생성 스크립트)는 그림이 아니라 대상이 아니다.
const FIGURE_SCRIPT = /(?:^|\/)figures\/(?:[^/]+\/)*gen_[^/]*\.py$|(?:^|\/)gen_[^/]*_(?:plt|tikz)\.py$|\.(?:tikz|drawio)$/i
const VISUAL_OUTPUT = /\.(?:html?|svg)$/i
// Confluence 저장 형식 html 은 문서 게시용이라 시각화가 아니다(2026-11-10 결정 C, html · htm 에만 적용). confluence 는 경로 전체에서 본다
// (문서 규칙 «이름에 confluence 가 든 폴더에 둔다»). .storage. 는 폴더 이름만으로 빠지지 않게 파일 이름에서만 보고, 파일 이름이 정확히
// storage.html 인 것도 받는다(scripts/skeleton-gate.sh · confluence_skeleton_check.py 사용법 표기 «<storage.html>»).
const VISUAL_EXEMPT: Array<(path: string, name: string) => boolean> = [
  path => /confluence/i.test(path),
  (_, name) => /\.storage\./i.test(name) || /^storage\.html?$/i.test(name),
]
// Bash 실행기(감싸는 명령을 벗긴 뒤 명령 자리의 낱말). 이 실행기는 첫 비옵션 인자가 실행 대상이다.
// drawio 는 옵션이 값을 받으므로(-f png) 인자 어디든 .drawio 이면 실행 대상으로 본다. uv 는 ruff 등 검사 도구도 부르므로 실행기가 아니다.
const RUNNERS = /^(?:python[\d.]*|bash|sh|zsh|node|bun|deno|pdflatex|xelatex|lualatex|latexmk)$/
const DRAWIO = /^(?:drawio|draw\.io)$/
// 실행기 앞을 감싸는 흔한 명령(뒤의 옵션도 벗긴다). timeout 은 시간 인자 하나를 더 받고, uv 는 «uv run [옵션] [--]» 꼴만 벗긴다.
const WRAPPERS = new Set(['env', 'nohup', 'time', 'timeout', 'exec', 'nice'])
// 값을 다음 낱말로 받는 옵션(옵션을 건너뛸 때 값도 건너뛴다). 근거: 이 저장소의 그림 실행 대표 꼴
// «uv run --offline --no-project --with matplotlib python -I …/gen_x_plt.py»(2026-11-10 측정 회차 실측)에서 --with 의 값이 명령 자리로 잡혀 놓쳤다.
// --옵션=값 꼴은 한 낱말이라 표에 없어도 된다. 표에 없는 옵션은 값 없는 옵션으로 본다.
const VALUE_OPTS: Record<string, string[]> = {
  uv: ['--with', '--with-requirements', '--with-editable', '--python', '-p', '--project', '--directory', '--env-file', '--extra', '--group', '--index'],
  python: ['-W', '-X'],
  timeout: ['-s', '-k', '--signal', '--kill-after'],
  nice: ['-n'],
  env: ['-u', '-C'],
}
// 판정에서 건너뛰는 낱말 길이 상한(긴 입력에서 정규식 비용을 막는다).
const MAX_WORD = 512

// 경로가 그림 스크립트 또는 시각화 산출물인가(문자열 검사만).
export function isVisualPath(path: string): boolean {
  if (FIGURE_SCRIPT.test(path)) return true
  if (!VISUAL_OUTPUT.test(path)) return false
  const name = path.split('/').pop() ?? ''

  return !(/\.html?$/i.test(path) && VISUAL_EXEMPT.some(f => f(path, name)))
}

// Bash 명령이 그림 스크립트를 실행하는가. 단순 명령(; | & 줄바꿈으로 나눈 토막)마다 낱말의 괄호 · 따옴표 · 세미콜론 · 붙은 리다이렉션을 떼고,
// 환경 변수 대입과 감싸는 명령을 벗긴 뒤 명령 자리의 낱말을 본다: 그 낱말이 그림 스크립트이면 대상, 실행기이면 첫 비옵션 인자가 그림 스크립트일 때 대상
// (python 의 -m · -c 는 스크립트 실행이 아니라 대상 아님). 앞 토막에서 figures 가 든 경로로 cd 했으면 gen_*.py 맨 이름도 그림 스크립트로 본다.
export function runsFigureScript(command: string): boolean {
  if (!/gen_|\.tikz|\.drawio/i.test(command)) return false
  let inFigures = false
  for (const part of command.split(/[;|&\n]/)) {
    const w = part.trim().split(/\s+/).filter(x => x.length <= MAX_WORD)
      .map(x => x.replace(/[<>].*$/, '').replace(/^[({'"]+|[)}'";]+$/g, '')).filter(Boolean)
    let i = 0
    for (;;) {
      while (i < w.length && /^[A-Za-z_][A-Za-z0-9_]*=/.test(w[i])) i++
      let kind = ''
      if (w[i] === 'uv' && w[i + 1] === 'run') {
        kind = 'uv'
        i += 2
      } else if (WRAPPERS.has(w[i] ?? '')) {
        kind = w[i]
        i += 1
      } else break
      while (w[i]?.startsWith('-')) i += VALUE_OPTS[kind]?.includes(w[i]) ? 2 : 1
      if (kind === 'timeout') i += 1
    }
    const head = w[i] ?? ''
    const base = head.split('/').pop() ?? ''
    const isScript = (x: string) => FIGURE_SCRIPT.test(x) || (inFigures && /^(?:\.\/)?gen_[^/]*\.py$/i.test(x))
    if (base === 'cd') {
      inFigures = /(?:^|\/)figures(?:\/|$)/i.test(w[i + 1] ?? '')
      continue
    }
    if (isScript(head)) return true
    if (DRAWIO.test(base) && w.slice(i + 1).some(x => /\.drawio$/i.test(x))) return true
    if (!RUNNERS.test(base)) continue
    const py = /^python/.test(base)
    let j = i + 1
    while (w[j]?.startsWith('-') && !(py && /^-[mc]/.test(w[j]))) j += VALUE_OPTS[py ? 'python' : base]?.includes(w[j]) ? 2 : 1
    if (w[j] !== undefined && !w[j].startsWith('-') && isScript(w[j])) return true
  }

  return false
}

const FIGURE_DENY =
  '그림이나 시각화 산출물을 만들기 전에 그릴 주체를 결정 팝업(mcp__decision-popup__ask)으로 먼저 물으십시오(사용자 결정 2026-10-28, 모든 그림 요청). 모바일 모드에서는 결정 팝업 대신 AskUserQuestion 으로 묻습니다. ' +
  '선택지: figure 스킬(코드로 그리기: TikZ · matplotlib · drawio) / Codex 이미지 생성(gen_gptimg.sh, main 이 실행 · 모델 · effort 1회 질문 · Codex 한도 3~5배) / Grok(grok-ask.sh --image, 결과는 JPG) / 연결된 다른 에이전트(ListAgents 의 다른 세션에 SendMessage 로 요청). ' +
  '팝업을 띄우고 턴을 끝낸 뒤, 사용자가 고른 대로 진행하십시오. 근거: skills/figure/SKILL.md § 그릴 주체 선택.'
const SUBAGENT_FIGURE_DENY =
  '서브에이전트는 사용자에게 물을 수 없습니다. 그림이나 시각화 산출물 작업을 여기서 멈추고 main 에 그릴 주체 질문을 요청하십시오(NEEDS_CONTEXT). ' +
  'main 은 결정 팝업으로 그릴 주체를 물은 뒤 다시 소집합니다. 근거: skills/figure/SKILL.md § 그릴 주체 선택.'
const MOBILE_DENY =
  '모바일 모드입니다(해제할 때까지): 설명은 채팅 글로 쓰고, 선택은 AskUserQuestion 으로 띄우십시오. 결정 팝업은 쓰지 않습니다. ' +
  '해제는 /mobile-mode off 명령(또는 띠의 📱 버튼)으로만 합니다. 사람 글로는 바뀌지 않습니다.'
const AGENT_DENY =
  '결정 팝업은 메인 대화에서만 띄웁니다. 서브 에이전트 · 엔진 작업(입력 제안 · 압축)은 팝업을 띄우지 말고 선택지를 메인에 돌려주십시오.'
const ASK_DENY =
  '결정 팝업이 있는 세션에서는 사용자 선택을 mcp__decision-popup__ask 로 띄웁니다(rules-lazy/answer-detail.md § 문제·선택지 보고 형식 «띄우는 도구»). ' +
  '같은 선택지를 결정 팝업으로 다시 띄우고 턴을 끝내십시오. 선택지 label 에는 값(모델 ID·effort 등)을 그대로 적습니다. ' +
  'AskUserQuestion 은 Confluence «게시 승인» 질문, 사용자가 이번 회차에 모바일·팝업 안 보임이라고 말했을 때만 씁니다.'

// AskUserQuestion 입력의 question · header · options[].label · options[].description 을 이어 붙인 판정 글. 모양이 깨져 있으면 빈 글.
function askText(e: unknown): string {
  const qs = (e as { questions?: unknown }).questions
  if (!Array.isArray(qs)) return ''
  const parts: string[] = []
  for (const q of qs as Record<string, unknown>[]) {
    if (!q || typeof q !== 'object') continue
    for (const v of [q.question, q.header]) if (typeof v === 'string') parts.push(v)
    if (Array.isArray(q.options)) {
      for (const o of q.options as Record<string, unknown>[]) {
        if (!o || typeof o !== 'object') continue
        for (const v of [o.label, o.description]) if (typeof v === 'string') parts.push(v)
      }
    }
  }

  return parts.join('\n')
}

// 작은 번호 글자(원문자 숫자·괄호 숫자·검은 원 숫자·원문자 알파벳)는 사용자 화면에서 작아 읽히지 않는다(2026-10-27 사용자 지시,
// intent/2026-10-27-no-circled-numbers.md). 받은 입력의 모든 문자열에서 «(3)» · «(a)» 꼴로 바꾸고 건수를 센다. 검사·표시는 바꾼 글 기준이다.
function smallNumber(cp: number): string | null {
  const spans: Array<[number, number, number, boolean]> = [
    [0x2460, 0x2473, 1, true], [0x2474, 0x2487, 1, true], [0x2776, 0x277f, 1, true], [0x2780, 0x2789, 1, true], [0x278a, 0x2793, 1, true],
    [0x24b6, 0x24cf, 0x41, false], [0x24d0, 0x24e9, 0x61, false],
  ]
  for (const [lo, hi, base, isDigit] of spans) {
    if (cp >= lo && cp <= hi) return `(${isDigit ? cp - lo + base : String.fromCharCode(base + cp - lo)})`
  }

  return null
}

export function replaceSmallNumbers(v: unknown): { value: unknown; count: number } {
  let count = 0
  const walk = (x: unknown): unknown => {
    if (typeof x === 'string') {
      let out = ''
      for (const ch of x) {
        const sub = smallNumber(ch.codePointAt(0) ?? 0)
        if (sub === null) out += ch
        else { out += sub; count++ }
      }

      return out
    }
    if (Array.isArray(x)) return x.map(walk)
    if (x && typeof x === 'object') return Object.fromEntries(Object.entries(x).map(([k, val]) => [k, walk(val)]))

    return x
  }
  const value = walk(v)

  return { value, count }
}

const INPUT_SCHEMA = {
  type: 'object',
  required: ['title', 'items'],
  properties: {
    title: { type: 'string', description: '팝업 제목(예: 열린 질문 5건)' },
    items: {
      type: 'array',
      minItems: 1,
      maxItems: 9,
      items: {
        type: 'object',
        required: ['id', 'title', 'scenario', 'options'],
        properties: {
          id: { type: 'string', description: '항목 표지(예: Q1)' },
          title: { type: 'string', description: '항목 제목 한 줄' },
          problem: { type: 'string', description: '무엇이 문제인지. 문단은 줄바꿈(\\n)으로 나눈다. 용어 정의는 terms 칸에' },
          scenario: { type: 'string', description: '문제 자체의 구체 예시: 이 문제가 실제로 어떤 장면에서 생기는지(수치·파일·장면). 선택지 example 은 이 장면에서 그 선택지를 고르면 어떻게 되는지로 쓴다' },
          terms: {
            type: 'array',
            maxItems: 8,
            description: '이 항목에 나오는 그 작업 문서 고유 용어마다 한 줄(«용어 | 설명» 표 한 행): meaning = 설명 열에 들어갈 뜻 + 예시 수치 하나. problem 안에 정의를 이어 붙이지 않는다',
            items: {
              type: 'object',
              required: ['term', 'meaning'],
              properties: {
                term: { type: 'string', description: '용어 이름' },
                meaning: { type: 'string', description: '설명 열에 들어갈 뜻 + 예시 수치 하나, 한 줄' },
              },
            },
          },
          experiments: {
            type: 'array',
            maxItems: 10,
            description: '이 항목의 제목·문제·선택지 어디에든 등장하는 모든 실험·판 이름과 새 판 별칭(예: 등록부 꼴의 판 id, P, R3)마다 무엇을·어떻게·왜를 각 한 줄. 출처(의뢰서·결정 기록·발사 기록)에서 옮기고 없으면 «기록 없음»',
            items: {
              type: 'object',
              required: ['name', 'what', 'how', 'why'],
              properties: {
                name: { type: 'string', description: '판 이름 또는 별칭(예: 판 id, R3)' },
                what: { type: 'string', description: '무엇을 한 판인지 한 줄' },
                how: { type: 'string', description: '어떻게 한 판인지 한 줄' },
                why: { type: 'string', description: '왜 한 판인지 한 줄' },
              },
            },
          },
          options: {
            type: 'array',
            minItems: 2,
            maxItems: 4,
            items: {
              type: 'object',
              required: ['label', 'example'],
              properties: {
                label: { type: 'string', description: '선택지 이름 한 줄(번호는 화면이 붙이므로 넣지 않는다)' },
                detail: { type: 'string', description: '무엇을·어떻게 한 줄' },
                pros: { type: 'string', description: '장점 한 줄' },
                cons: { type: 'string', description: '단점 한 줄' },
                example: { type: 'string', description: '위 scenario 장면에서 이 선택지를 고르면 실제로 어떻게 되는지 구체 예시 한 줄(필수, 수치·파일·장면). 기존 실험(판) 하나를 고르는 항목이면 그 실험의 무엇을·어떻게·왜를 두 줄로 요약해 « / » 로 이어 쓴다(판 이름만 금지, 2026-10-23 사용자 지시)' },
              },
            },
          },
        },
      },
    },
  },
} as const

// 판 이름 꼴은 코드에 두지 않고 하네스 프로젝트 등록부(config/projects/<프로젝트>.json 의 decision_popup.run_name_patterns)에서 읽는다.
// 모든 프로젝트 파일의 꼴을 합쳐 모든 세션에 건다: 세션의 cwd 가 워크스페이스 뿌리나 상위 폴더인 경우가 많아(2026-11-10 실측)
// mod 가 세션의 프로젝트를 알 수 없기 때문이다. 등록된 꼴이 없거나 파일 · 정규식이 깨지면 그 꼴만 빠지고 팝업은 그대로 뜬다.
// \b 는 ASCII 기준이라 «<판>를» 처럼 한글 조사가 붙어도 잡힌다.
// 등록부 꼴 방어(2026-11-10 외부 검증 2회): `(a+)+$` 같은 꼴이 a 27개 + `!` 입력에 11.9초 걸린 재현이 있었다.
// 처음 넣은 금지 목록(중첩 수량자 · 역참조 거름)은 같은 계열의 다른 꼴을 두 번 놓쳤다: 묶음을 한 겹 더 싼 `((b+))+$` 와
// 겹치는 갈래를 반복하는 `(b|b)+$` 가 통과해 b 26개 + `!` 에 1.2~1.3초 걸렸다(2차 재검토 R1). 그래서 허용 문법으로 바꿨다.
// 꼴을 토큰으로 끝까지 읽어 아래에 없는 토큰이 하나라도 있으면 그 꼴을 버린다.
//   위치: \b ^ $ / 원자: 영숫자 · - · _ 글자 그대로, \d, 부정 없는 단순 문자 클래스(글자 · 범위만. 클래스 안의 + . 는 글자다)
//   수량자는 원자에만: ? {m} {m,n}(n ≤ 4). + * {n,} 는 받지 않는다.
//   묶음은 비캡처 (?:…) 한 겹만, 안에는 원자와 그 수량자만, 뒤에는 ? 만. 갈래 | · 임의 글자 . · 캡처 묶음 · 역참조 · 전후방 탐색은 없다.
//   갈래 수의 곱: 수량자마다 (n − m + 1), ? 마다 2(원자에 붙든 묶음에 붙든)를 모두 곱한 값이 RUN_CHOICE_MAX(64) 이하여야 한다.
// 이 문법에서는 일치 길이가 꼴 길이 × 4 이하로 묶이고, 시작 위치마다 엔진이 시도하는 경로 수가 위 갈래 수의 곱으로 묶인다.
// 처음엔 «수량자 붙은 원자 4개 이하» 로 셌는데 묶음 뒤 ? 가 계수에서 빠져, {0,4} 4개 뒤 (?:a)? 6개를 이은 61자 꼴이
// 같은 글자 4,999개 + 다른 글자 하나에 978ms 걸렸다(2026-11-10 qa 반증). 그래서 개수 대신 곱에 상한을 둔다(지금 등록된 꼴의 곱은 18).
// 대조 시간이 글 길이에 선형이라 칸을 자르지 않고 전체 글을 대조한다(자르면 뒤의 판 이름을 놓치고 자른 자리에 가짜 낱말 경계가 생겼다, R3 · R4).
// 둘째 방어로 빈 글 · 평범한 낱말(5자 이상 포함, R2) · 평범한 문장(흔한 짧은 낱말 · 두 자리 수 · 연도 · 대문자 약어 · 한글 낱말)
// 어디에든 맞는 꼴도 버린다. 버린 까닭은 off 에 모아 도구 결과에 한 줄로 알린다.
export const RUN_PATTERN_MAX = 64
const RUN_QUANT_MAX = 4
const RUN_CHOICE_MAX = 64
const RUN_SAMPLES = ['', 'the', '모델', '2026', 'a', 'hello', 'model', '학습데이터', '20261110',
  'This is a plain sentence: we trained the model on 12 of 30 items in 2026 with an API and a GPU.',
  'We compare at most two of them to see if it works, and it did.',
  'There are 12 items in 3 groups, so a 4 is left over by the end of May.',
  '오늘 11월 10일에 API를 호출해서 모델을 학습했고 결과는 좋다. 이 값은 내 표에 둔다.',
  '결정: 이번 실험은 검증데이터기준으로 다시 정리했습니다.']
const RUN_LIT = /^[A-Za-z0-9_-]$/

// p[i] 에서 원자 하나를 읽고 끝 위치를 돌려준다(원자가 아니면 -1).
function runAtomEnd(p: string, i: number): number {
  if (p.startsWith('\\d', i)) return i + 2
  if (RUN_LIT.test(p[i] ?? '')) return i + 1
  if (p[i] !== '[' || p[i + 1] === '^') return -1
  let j = i + 1
  while (j < p.length && p[j] !== ']') {
    if ('\\[^'.includes(p[j])) return -1
    j++
  }
  return j > i + 1 && j < p.length ? j + 1 : -1
}

// p[i] 에서 수량자를 읽고 [끝 위치, 갈래 수] 를 돌려준다(수량자가 없으면 [i, 1], 문법 밖이면 [-1, 0]).
function runQuant(p: string, i: number): [number, number] {
  if (p[i] === '?') return [i + 1, 2]
  if (p[i] !== '{') return [i, 1]
  const m = /^\{(\d+)(?:,(\d+))?\}/.exec(p.slice(i))
  if (!m) return [-1, 0]
  const lo = Number(m[1])
  const hi = Number(m[2] ?? m[1])
  return lo <= hi && hi <= RUN_QUANT_MAX ? [i + m[0].length, hi - lo + 1] : [-1, 0]
}

export function runPatternProblem(p: string): string | null {
  if (p.length === 0 || p.length > RUN_PATTERN_MAX) return `길이 ${p.length}자(1~${RUN_PATTERN_MAX}자만 받음)`
  const badQuant = (at: number) => `수량자는 ? · {m} · {m,n}(n ≤ ${RUN_QUANT_MAX})만(${at + 1}번째 글자)`
  let choices = 1
  let i = 0
  while (i < p.length) {
    if (p.startsWith('\\b', i)) { i += 2; continue }
    if (p[i] === '^' || p[i] === '$') { i += 1; continue }
    if (p.startsWith('(?:', i)) {
      let j = i + 3
      while (j < p.length && p[j] !== ')') {
        const a = runAtomEnd(p, j)
        if (a < 0) return `묶음 안에는 원자만(${j + 1}번째 글자 «${p[j]}»)`
        const [q, k] = runQuant(p, a)
        if (q < 0) return badQuant(a)
        choices *= k
        j = q
      }
      if (j >= p.length || j === i + 3) return '빈 묶음이나 닫히지 않은 묶음'
      i = j + 1
      if (p[i] === '?') { i++; choices *= 2 }
      else if (i < p.length && '*+{'.includes(p[i])) return '묶음 뒤에는 ? 만'
      continue
    }
    const a = runAtomEnd(p, i)
    if (a < 0) return `허용 문법 밖의 글자 «${p[i]}»(${i + 1}번째)`
    const [q, k] = runQuant(p, a)
    if (q < 0) return badQuant(a)
    choices *= k
    i = q
  }
  if (choices > RUN_CHOICE_MAX) return `갈래 수의 곱 ${choices}(${RUN_CHOICE_MAX}까지만)`
  let re: RegExp
  try {
    re = new RegExp(p)
  } catch {
    return '정규식 오류'
  }
  const hit = RUN_SAMPLES.map(s => re.exec(s)).find(m => m !== null)
  return hit ? `아무 글에나 맞음(«${hit[0]}»)` : null
}

export async function loadRunNamePatterns(list: (p: string) => Promise<readonly { name: string }[]>,
  readFile: (p: string) => Promise<unknown>, projectsDir: string): Promise<{ patterns: RegExp[]; off: string[] }> {
  const patterns: RegExp[] = []
  const off: string[] = []
  let names: string[] = []
  try {
    names = (await list(projectsDir)).map(x => x.name).filter(n => n.endsWith('.json')).sort()
  } catch {
    return { patterns, off: ['등록부 폴더를 읽지 못함'] }
  }
  for (const n of names) {
    try {
      const cfg = JSON.parse(String(await readFile(`${projectsDir}/${n}`))) as { decision_popup?: { run_name_patterns?: unknown } }
      const pats = cfg.decision_popup?.run_name_patterns
      for (const p of Array.isArray(pats) ? pats : []) {
        const why = typeof p === 'string' ? runPatternProblem(p) : '문자열 아님'
        if (why) off.push(`${n} 의 꼴 하나 제외(${why})`)
        else patterns.push(new RegExp(p as string, 'g'))
      }
    } catch {
      off.push(`${n} 를 읽지 못함`)
    }
  }
  return { patterns, off }
}

function validate(raw: unknown, runNames: readonly RegExp[] = []): DecisionRequest | string {
  const r = raw as { title?: unknown; items?: unknown }
  if (typeof r.title !== 'string' || !Array.isArray(r.items) || r.items.length === 0) {
    return 'title(문자열)과 items(1개 이상)가 필요합니다'
  }
  const items: DecisionItem[] = []
  for (const it of r.items as DecisionItem[]) {
    if (!it || typeof it.id !== 'string' || typeof it.title !== 'string' || !Array.isArray(it.options)) {
      return '각 항목에 id·title·options 가 필요합니다'
    }
    if (it.options.length < 2 || it.options.length > 4) {
      return `${it.id}: 선택지는 2~4개여야 합니다`
    }
    // 장단점 표 아래 «선택지별 예시» 는 항상 그린다(개정 17 보충, 2026-10-21 사용자 «항상»): 예시가 빈 선택지는 받지 않는다.
    const noExample = it.options.findIndex(o => !o || typeof o.label !== 'string' || typeof o.example !== 'string' || !o.example.trim())
    if (noExample >= 0) {
      return `${it.id}: ${noExample + 1}번 선택지에 label 과 example(구체 예시 한 줄)이 필요합니다`
    }
    // 문제 자체의 구체 예시(개정 19): 필수. 선택지별 예시는 이 장면의 하위 단계로 그려진다.
    const scenario = typeof (it as { scenario?: unknown }).scenario === 'string' ? clean((it as { scenario: string }).scenario).trim() : ''
    if (!scenario) {
      return `${it.id}: scenario(문제 자체의 구체 예시 한 줄: 이 문제가 실제로 생기는 장면)가 필요합니다`
    }
    // 용어 칸(개정 19): 선택. 있으면 원소마다 term·meaning 이 비어 있지 않아야 한다.
    const rawTerms: unknown = (it as { terms?: unknown }).terms
    if (rawTerms !== undefined && (!Array.isArray(rawTerms) || rawTerms.length > 8)) {
      return `${it.id}: terms 는 최대 8개의 배열이어야 합니다`
    }
    const terms: Array<{ term: string; meaning: string }> = []
    for (const [i, x] of ((rawTerms ?? []) as Partial<Record<'term' | 'meaning', unknown>>[]).entries()) {
      const cell = (v: unknown) => (typeof v === 'string' ? clean(v).trim() : '')
      const row = { term: cell(x?.term), meaning: cell(x?.meaning) }
      if (!row.term || !row.meaning) {
        return `${it.id}: 용어 칸(terms) ${i + 1}번 행의 term·meaning 은 모두 비어 있지 않은 글이어야 합니다`
      }
      terms.push(row)
    }
    const problem = typeof it.problem === 'string' ? cleanPara(it.problem) : undefined
    // 화면이 «1) » 번호를 붙이므로, 모델이 label 앞에 붙여 보낸 번호(«1) », «2. », «(3) »)는 뗀다(2026-10-21 «1) 1)» 겹침).
    // «.» 는 뒤에 공백이 있을 때만 번호로 본다: «2.5배 방식»·«1.0 버전» 같은 이름을 지키기 위해서다(qa 2026-10-21).
    const options = it.options.map(o => {
      const label = clean(o.label)

      return {
        label: label.replace(/^\s*\(?\d+(?:\)\s*|\.\s+)/, '') || label,
        detail: optClean(o.detail), pros: optClean(o.pros), cons: optClean(o.cons), example: clean(o.example),
      }
    })
    // 실험 정리 표(2026-10-23 사용자 지시): 0e39c90ba 문구 규칙 뒤 같은 날 재발 → 도구 거부로 구조화.
    // 판 이름 꼴(등록부 decision_popup.run_name_patterns)이 글에 나오면 experiments 에 같은 이름이 있어야 하고, 칸이 비어도 거부한다. 별칭(P·R3)은 기계가 못 찾는다.
    const rawExp: unknown = (it as { experiments?: unknown }).experiments
    if (rawExp !== undefined && (!Array.isArray(rawExp) || rawExp.length > 10)) {
      return `${it.id}: experiments 는 최대 10개의 배열이어야 합니다`
    }
    const experiments: DecisionExperiment[] = []
    for (const [i, x] of ((rawExp ?? []) as Partial<Record<keyof DecisionExperiment, unknown>>[]).entries()) {
      const cell = (v: unknown) => (typeof v === 'string' ? clean(v).trim() : '')
      const row = { name: cell(x?.name), what: cell(x?.what), how: cell(x?.how), why: cell(x?.why) }
      if (!row.name || !row.what || !row.how || !row.why) {
        return `${it.id}: 실험 정리 표(experiments) ${i + 1}번 행의 name·what·how·why 는 모두 비어 있지 않은 글이어야 합니다`
      }
      experiments.push(row)
    }
    // 칸 전체를 대조하고(허용 문법이라 선형), 찾은 이름과 표의 이름은 둘 다 소문자로 맞춰 비교한다.
    const runs = (s: string) => runNames.flatMap(re => s.match(re) ?? [])
    const lc = (s: string) => s.toLowerCase()
    const known = new Set(experiments.flatMap(x => [lc(x.name), ...runs(x.name).map(lc), ...runs(lc(x.name)).map(lc)]))
    const fields = [clean(it.title), problem ?? '', scenario, ...terms.flatMap(t => [t.term, t.meaning]), ...options.flatMap(o => [o.label, o.detail ?? '', o.pros ?? '', o.cons ?? '', o.example])]
    const lost = [...new Set(fields.flatMap(runs))].filter(n => !known.has(lc(n)))
    if (lost.length > 0) {
      return `${it.id}: 실험 정리 표(experiments)에 없는 판: ${lost.join(', ')} — 항목에 나오는 판·별칭마다 무엇을·어떻게·왜 한 줄씩 넣으십시오`
    }
    items.push({ id: clean(it.id), title: clean(it.title), problem, scenario, ...(terms.length > 0 ? { terms } : {}), options, ...(experiments.length > 0 ? { experiments } : {}) })
  }

  return { title: clean(r.title), items }
}

// 모델이 보낸 글은 받을 때 한 번 정리한다(2026-10-21 security·qa): 줄 구분 문자는 « / » 로(oneLine), 그 밖의 제어 문자(C0·DEL·C1)와
// 방향 제어 문자(U+202A~202E · U+2066~2069)는 지운다. 정리하지 않으면 ① 엔진이 제어 문자 든 글을 그리기 거부하고(«a text child holds a
// control character») ② 확정·닫힘 메시지의 줄 꼴을 꾸며 외부 모델 게이트(scripts/external-model-gate.py popup_answers)를 속일 수 있다.
const DROP = (c: number) => c < 0x20 || (c >= 0x7f && c <= 0x9f) || (c >= 0x202a && c <= 0x202e) || (c >= 0x2066 && c <= 0x2069)
function clean(s: string): string {
  let out = ''
  for (const ch of oneLine(s)) if (!DROP(ch.codePointAt(0) ?? 0)) out += ch

  return out
}
// problem 전용(개정 19): 줄바꿈(\n, CRLF·CR 포함)은 문단 구분으로 남기고 줄마다 clean, 연속 빈 줄은 하나로, 앞뒤 공백·빈 줄은 뗀다.
function cleanPara(s: string): string {
  const out: string[] = []
  for (const line of String(s).split(/\r\n|\r|\n/)) {
    const t = clean(line).trim()
    if (t || (out.length > 0 && out[out.length - 1] !== '')) out.push(t)
  }
  while (out.length > 0 && out[out.length - 1] === '') out.pop()

  return out.join('\n')
}
// 문단 목록(빈 줄 제외). 그리기와 창 높이 계산이 같이 쓴다.
const paragraphs = (p: string | undefined): string[] => (p ? p.split('\n').filter(Boolean) : [])
const optClean = (s: string | undefined) => (typeof s === 'string' ? clean(s) : undefined)

// 글자색: 보색 짝으로 칸끼리 갈라 본다(2026-10-21 사용자 지시). 제목 파랑 ↔ 항목 번호·이동 주황, 문제 노랑 ↔ 안 고른 선택지 보라,
// 장점 초록 ↔ 단점 분홍, 고른 선택지 초록. 어두운·밝은 테마마다 값을 따로 두고(하네스 띠 팔레트와 같은 계열) Claude Code 테마 이름이
// light 로 시작하면 밝은 팔레트를 쓴다. 읽기 실패는 어두운 팔레트.
// 선택지 설명(detail)은 흐린 글자만으로는 안 보인다는 지적(2026-10-21)에 따라 바탕을 깔고 그 위에 대비되는 글자색(detailFg/detailBg)을 쓴다.
// 장점·단점은 선택지마다 따로 두지 않고 페이지 아래에 «선택지 · 장점 · 단점» 테두리 표 하나로 모은다(2026-10-21 사용자 지시).
type Palette = {
  title: string; id: string; problem: string; label: string; picked: string; unpicked: string; detail: string
  detailFg: string; detailBg: string; border: string; pros: string; cons: string; nav: string; missing: string
}
const PALETTES: Record<'dark' | 'light', Palette> = {
  dark: { title: '#A9D8FF', id: '#FFC4A3', problem: '#F6E3A1', label: '#ECEBF5', picked: '#A8E6C1', unpicked: '#C9B8FF', detail: '#8D8AA6',
    detailFg: '#FFE7B3', detailBg: '#353A5C', border: '#6B6F8E', pros: '#A8E6C1', cons: '#FFA8C5', nav: '#FFC4A3', missing: '#FFA8C5' },
  light: { title: '#2F6FA8', id: '#B5582B', problem: '#94740F', label: '#242132', picked: '#2E8A57', unpicked: '#6A4FC0', detail: '#8A879C',
    detailFg: '#3A2E6E', detailBg: '#E6E1F7', border: '#B7B2CC', pros: '#2E8A57', cons: '#C23B6A', nav: '#B5582B', missing: '#C23B6A' },
}

// 창 높이: 머리 6줄(+문제 문단마다 2줄) + 용어 표(제목 1 · 테두리 2 · 머리 1 · 용어마다 1) + 선택지마다 2줄(이름 · 설명) + 직접 입력 2줄
// + 장단점 표(테두리 2 · 머리 1 · 선택지마다 1) + 문제 예시 2줄 + 예시 블록(제목 1 · 선택지마다 1). 40줄을 넘으면 창이 스크롤한다.
// 표 구분선: 머리 아래 1 + 행 사이 (행 수 − 1) = 행 수만큼 줄이 더 든다(장단점 표 선택지 수 · 용어 수 · 실험 수).
function wantedRows(req: DecisionRequest): number {
  const per = req.items.map(it => 6 + paragraphs(it.problem).length * 2 + (it.terms ? it.terms.length * 2 + 4 : 0) + 2 + it.options.length * 5 + 3 + 2 + 1 + (it.experiments ? it.experiments.length * 2 + 3 : 0))

  return Math.min(40, Math.max(14, ...per, req.items.length + 7))
}

// 답 메시지는 항목당 한 줄이다. 외부 모델 게이트(scripts/external-model-gate.py popup_answers)가 «- » 줄의 마지막 «: » 뒤를
// 사용자 답으로 읽으므로, 모델이 쓴 제목·표지·이름에 줄바꿈이 있으면 가짜 «- » 줄을 만들 수 있다. 줄바꿈은 « / » 로 바꾼다(2026-10-21).
// 줄 구분 문자: LF·VT·FF·CR·FS·GS·RS·US·NEL·LS·PS. Python splitlines() 가 나누는 문자를 모두 덮는다(qa 2026-10-21).
const LINE_BREAK = (c: number) => (c >= 0x0a && c <= 0x0d) || (c >= 0x1c && c <= 0x1e) || c === 0x1f || c === 0x85 || c === 0x2028 || c === 0x2029
const oneLine = (s: string) => {
  let out = ''
  for (const ch of String(s)) out += LINE_BREAK(ch.codePointAt(0) ?? 0) ? ' / ' : ch

  return out.replace(/ \/ (?:\s*\/ )+/g, ' / ')
}

// 한 항목의 답을 한 줄 글로. 직접 입력도 같은 방식으로 한 줄로 싣는다.
function pickedText(it: DecisionItem, k: number | undefined, free: string | undefined): string | undefined {
  if (k === FREE && free !== undefined) return `직접 입력) ${oneLine(free)}`
  const opt = k === undefined ? undefined : it.options[k]

  return opt ? `${k! + 1}) ${oneLine(opt.label)}` : undefined
}

function answerText(req: DecisionRequest, chosen: Record<string, number>, free: Record<string, string>): string {
  const lines = req.items.map(it => `- ${oneLine(it.id)} ${oneLine(it.title)}: ${pickedText(it, chosen[it.id], free[it.id]) ?? '(미선택)'}`)

  return [`[결정 팝업 확인] ${oneLine(req.title)}`, ...lines].join('\n')
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.tool.register({
      name: TOOL,
      description:
        '사용자에게 결정 항목(각 2~4개 선택지)을 팝업으로 띄운다. 항목마다 scenario(문제 자체의 구체 예시)는 필수이고, ' +
        '선택지 example 은 그 장면에서 고르면 어떻게 되는지 적는다(장단점·용어·실험 표 아래에 «예시(문제)» 와 그 하위 선택지별 예시로 보인다). 항목마다 사용자가 글로 답하는 «직접 입력» 칸이 ' +
        '번호 선택지 바로 뒤에 붙는다(답 메시지에 «직접 입력) 글» 로 들어온다). 사용자가 항목마다 고른 뒤 확인하면 ' +
        '답이 «[결정 팝업 확인]» 메시지로 이 세션에 들어온다. 호출한 뒤에는 턴을 끝내고 그 메시지를 기다린다. ' +
        '답이 오지 않은 팝업이 열려 있으면 새 항목은 그 팝업의 다음 페이지로 붙는다(합계 18개까지). ' +
        '선택지 순서는 문서·합의 등장 순으로 두고 추천 표시를 넣지 않는다. 기존 실험(판) 가운데 하나를 고르게 할 때는 ' +
        '선택지마다 example 에 그 실험이 무엇을·어떻게·왜 한 것인지 두 줄 요약을 « / » 로 이어 적는다(판 이름만 적지 않는다). ' +
        '항목에 등장하는 모든 실험·판·별칭은 experiments 칸에 무엇을·어떻게·왜 각 한 줄(용어 표와 예시 사이에 표로 보인다). ' +
        '등록된 판 이름 꼴이 나오는데 칸에 없으면 거부된다. 별칭(P·Q·R3)은 자동으로 못 찾으니 빠짐없이 적는다. ' +
        '원문자 숫자(①) · 원문자 알파벳은 쓰지 않는다(넣으면 (1) 로 바뀌고 T41 에 적힌다). 처음 나오는 줄임말은 풀어 쓴다. ' +
        '문서 고유 용어(채점·통과·음성·관문 등)는 terms 칸에 용어마다 한 줄(장단점 표 아래 «용어 | 설명» 표로 보인다, 설명 열에 뜻 + 예시 수치 하나)로 적고, problem 은 문단을 줄바꿈으로 나눈다.',
      inputSchema: INPUT_SCHEMA,
      isDeferred: false,
    })
    await $.command.register({
      name: 'decision',
      description: '열려 있던 결정 팝업을 다시 띄운다',
    })
    await $.command.register({
      name: 'mobile-mode',
      description: '이 세션의 모바일 모드를 켜고 끕니다(켜면 결정 팝업 대신 선택 질문, 인자 없으면 뒤집기)',
      argumentHint: '[on|off|켜기|끄기]',
      immediate: true,
    })
    // 재시작 복원: 상태 파일이 on 이면 되살린 뒤, 띠 버튼이 처음부터 맞는 글자를 보이게 현재 상태를 한 번 써 둔다
    if (await readMobileFile($)) await update($, mobileMode, () => true)
    await writeMobileFile($, await read($, mobileMode))

    return next(e)
  })

  // 메인 대화가 아닌 곳(서브 에이전트 · teammate · 워크플로 에이전트 · 엔진 포크)의 호출은 팝업을 열지 않고 거부한다(사용자 결정 S1y, 2026-11-03).
  // 근거: 한 학습 세션에서 그 세션이 부르지 않은 팝업(«다음 입력 제안 칸 형식 확인»)이 11-02 · 11-03 두 번 사용자에게 떴다. 입력창 «다음 입력 제안»을
  // 만드는 엔진 포크가 대화 사본으로 돌며 «고르는 것은 전부 결정 팝업» 규칙을 따라 이 도구를 불러 열린 팝업의 다음 쪽에 붙은 것으로 추정한다.
  // 판정: tool.call 입력의 AgentLoop.agentId 는 메인 루프에는 없고 서브 에이전트 · teammate · 워크플로 에이전트 · 엔진 포크(압축 · 메모리)에는 있다.
  // 막은 호출은 blocked.tsv 에 한 줄 남겨 원인이 엔진 포크인지 나중에 확인한다(기록 실패는 거부를 막지 않는다).
  on('tool.call', { tool: `mcp__${PLUGIN}__${TOOL}` }, async ($, e) => {
    const agentId = (e as { agentId?: unknown }).agentId
    if (typeof agentId === 'string' && agentId !== '') {
      try {
        const home = String((await $.env.get('HOME')) || '')
        if (home.startsWith('/')) {
          const path = `${home}/.claude/_usage/decision-popup/blocked.tsv`
          // 탭 · 줄 구분 문자(LINE_BREAK)는 한 칸으로: 한 줄 · 네 칸 꼴을 지킨다.
          const title = Array.from(String((e as { title?: unknown }).title ?? ''), ch => (ch === '\t' || LINE_BREAK(ch.codePointAt(0) ?? 0) ? ' ' : ch)).join('').slice(0, 80)
          const prev = await $.fs.read(path).catch(() => '')
          await $.fs.write(path, `${prev}${new Date().toISOString()}\t${await $.session.id()}\t${agentId}\t${title}\n`)
        }
      } catch {
        // 기록 실패는 거부를 막지 않는다
      }

      return { deny: AGENT_DENY }
    }
    try {
      if (await read($, mobileMode)) return { deny: MOBILE_DENY }
    } catch {
      // 기억 읽기 실패는 팝업을 막지 않는다
    }
    const fixed = replaceSmallNumbers(e)
    let runNames: RegExp[] = []
    let runOff: string[] = []
    try {
      const home = String((await $.env.get('HOME')) || '')
      if (home.startsWith('/') && home !== '/') {
        const got = await loadRunNamePatterns(p => $.fs.list(p), p => $.fs.read(p), `${home}/.claude/config/projects`)
        runNames = got.patterns
        runOff = got.off
      } else {
        runOff = ['HOME 을 알 수 없음']
      }
    } catch {
      runOff = ['등록부를 읽지 못함']   // 판 이름 검사만 끄고 팝업은 띄운다
    }
    const req = validate(fixed.value, runNames)
    if (typeof req === 'string') {
      return { deny: `결정 팝업 입력 오류: ${req}` }
    }
    // 열린 팝업에 붙일 때의 항목 상한은 T41 적립보다 먼저 본다: 거부된 호출이 T41 을 남기지 않게(2026-10-27 qa FAIL 수정).
    const cur = await read($, request)
    if (cur && cur.items.length + req.items.length > MAX_ITEMS) {
      return {
        deny: `결정 팝업 입력 오류: 열린 팝업(«${cur.title}»)에 답을 받기 전이라 항목을 더 붙일 수 없습니다(합계 ${cur.items.length + req.items.length}개 > ${MAX_ITEMS}). 열린 팝업의 답을 받은 뒤 다시 띄우십시오.`,
      }
    }
    // 판 이름 검사가 꺼졌거나 꼴 일부가 빠졌으면 모델에게 돌아가는 결과에만 한 줄 알린다(팝업 본문은 그대로).
    // 쓸 수 있는 꼴이 0개면 «꺼져 있음», 남은 꼴이 있으면 그 꼴로 검사했다고 버린 건수와 함께 알린다(R6).
    let note = runOff.length === 0 ? ''
      : runNames.length === 0 ? ` 판 이름 검사가 꺼져 있음: ${runOff.join(' · ')}.`
        : ` 판 이름 꼴 ${runOff.length}건을 버리고 남은 꼴 ${runNames.length}개로 검사함: ${runOff.join(' · ')}.`
    if (fixed.count > 0) {
      note += ` 작은 번호 글자 ${fixed.count}건을 (n) 꼴로 바꿔 띄웠습니다. 다음부터 1) · 판1 처럼 일반 글자로 쓰십시오(rules-lazy/answer-detail.md § 원문자 금지).`
      // T41 적립(역할 main, 차원 지시 준수). 실제로 띄운 팝업만, 세션당 T41_CAP 회까지 적는다:
      // 거부된 입력이나 일부러 반복한 호출이 T41 반복 문턱을 헛되이 넘기지 않게(2026-10-27 security 낮음).
      // 실패·시간 초과는 팝업을 막지 않는다(fail-open), 3초 상한.
      try {
        const logged = await read($, t41Logged)
        const home = String((await $.env.get('HOME')) || '')
        if (logged < T41_CAP && home.startsWith('/')) {
          await update($, t41Logged, n => n + 1)
          await $.process.run(
            ['bash', `${home}/.claude/scripts/t41-append.sh`, 'main', '지시 준수', `결정 팝업에 작은 번호 글자 ${fixed.count}건(자동 치환): ${clean(req.title).slice(0, 40)}`],
            { timeoutMs: 3000 },
          )
        }
      } catch {
        // 기록 실패는 팝업을 막지 않는다
      }
    }
    // 답이 오지 않은 팝업(request 가 남아 있음)이 있으면 새 항목을 그 뒤 페이지로 붙인다(intent/2026-10-27-popup-append-to-open.md).
    // 덮어쓰면 앞 팝업의 답이 사라지는 실사고(2026-10-27). 답·직접 입력·보는 페이지는 그대로 둔다.
    let shown: DecisionRequest = req
    const renamed: string[] = []
    // 쓰기 직전에 다시 읽는다: 위의 T41 기록(await)을 기다리는 사이 같은 턴의 다른 호출이 붙였거나 사용자가 확인했을 수 있다(security 낮음).
    const live = cur ? await read($, request) : null
    if (live) {
      if (live.items.length + req.items.length > MAX_ITEMS) {
        return { deny: `결정 팝업 입력 오류: 열린 팝업(«${live.title}»)에 항목을 더 붙일 수 없습니다(합계 ${live.items.length + req.items.length}개 > ${MAX_ITEMS}). 열린 팝업의 답을 받은 뒤 다시 띄우십시오.` }
      }
      const used = new Set(live.items.map(i => i.id))
      const added = req.items.map(i => {
        let id = i.id
        for (let k = 2; used.has(id); k++) id = `${i.id}-${k}`
        used.add(id)
        if (id !== i.id) renamed.push(`${i.id} → ${id}`)

        return id === i.id ? i : { ...i, id }
      })
      // 이어 붙인 제목은 TITLE_MAX 자로 자른다: 창 제목·확인 메시지 머리줄·안내 문구에 되풀이해 실린다(security 낮음).
      const title = `${live.title} · ${req.title}`
      shown = { ...live, title: title.length > TITLE_MAX ? `${title.slice(0, TITLE_MAX - 1)}…` : title, items: [...live.items, ...added] }
      await update($, request, () => shown)
    } else {
      await update($, request, () => req)
      await update($, answers, () => ({}))
      await update($, texts, () => ({}))
      await update($, page, () => 0)
    }
    const opened = await $.ui.open({
      id: PANE,
      title: `결정: ${shown.title}`,
      focus: true,
      closeOnEscape: true,
      holdToasts: true,
      rows: wantedRows(shown),
    })
    await update($, unplaced, () => !opened.isPlaced)
    const lead = live
      ? `열린 결정 팝업(«${live.title}»)에 답이 아직 없어 새 항목 ${req.items.length}개를 그 팝업의 다음 페이지로 붙였습니다. ` +
        (renamed.length ? `겹친 항목 이름은 바꿨습니다(${renamed.join(', ')}). 답 메시지에서는 바뀐 이름으로 읽으십시오. ` : '') +
        '사용자가 확인하면 두 묶음의 답이 «[결정 팝업 확인]» 메시지 하나로 들어옵니다. '
      : ''
    if (!opened.isPlaced) {
      return {
        result: `${lead}팝업을 아직 그리지 못했습니다(${opened.reason}). 터미널을 넓히거나 /decision 으로 다시 열 수 있습니다. ` +
          '확인되면 «[결정 팝업 확인]» 메시지가 들어옵니다.' + note,
      }
    }
    if (live) return { result: `${lead}지금 턴을 끝내고 기다리십시오.${note}` }

    return {
      result: `결정 팝업을 띄웠습니다(${req.items.length}개 항목). 사용자가 모두 고르고 확인하면 «[결정 팝업 확인]» 메시지가 새로 들어옵니다. 지금 턴을 끝내고 기다리십시오.${note}`,
    }
  })

  // 마지막 «사용자 메시지» 판정 기억: 글은 바꾸지 않고 그대로 통과시킨다.
  // 사람이 쓴 글(직접 입력 composer · Remote Control bridge)만 센다. 피어 세션·작업 알림·예약 실행·플러그인 글이
  // 모바일 예외를 거짓으로 켜거나 진짜 예외를 지우지 않게 한다(2026-10-27 security 낮음).
  on('prompt.submit', async ($, e, next) => {
    try {
      const said = hiddenFromPrompt((e as { origin?: { kind?: string } }).origin?.kind, e.text)
      if (said !== null) await update($, userSaidHidden, () => said)
      if (isHumanPrompt((e as { origin?: { kind?: string } }).origin?.kind, e.text)) await update($, answeredSinceHuman, () => false)
    } catch {
      // 기억 실패는 글 전달을 막지 않는다
    }

    return next(e)
  })

  // AskUserQuestion 사전 차단: 예외 셋(게시 승인 · 직전 사용자 글의 모바일/안 보임 · 마지막 팝업이 안 놓임) 외에는 팝업으로 돌려보낸다.
  // 판정 중 오류가 나면 통과(fail-open)시켜 도구 호출 자체를 깨뜨리지 않는다.
  on('tool.call', { tool: 'AskUserQuestion' }, async ($, e, next) => {
    try {
      const exempt =
        PUBLISH_APPROVAL.test(askText(e)) ||
        (await read($, userSaidHidden)) ||
        (await read($, unplaced)) ||
        (await read($, mobileMode))
      if (!exempt) return { deny: ASK_DENY }
    } catch {
      // fail-open
    }
    const res = await next(e)
    // AskUserQuestion 이 답을 받고 끝나면 팝업 확인과 같이 그릴 주체 답의 근거로 친다(거부 · 오류는 제외).
    try {
      if (!res.deny && !res.isError) await update($, answeredSinceHuman, () => true)
    } catch {
      // 기억 실패는 결과 전달을 막지 않는다
    }
    // 고른 선택지 이름이 «잘못된 막힘» 과 같으면 표시 파일을 남긴다(writeWrongBlockMarker). 실패해도 결과 전달은 그대로다.
    try {
      if (!res.deny && !res.isError && askPickedWrongBlock(res.result)) await writeWrongBlockMarker($)
    } catch {
      // 표시 실패는 결과 전달을 막지 않는다
    }

    return res
  })

  // 그릴 주체 사전 차단(대상 1~4, 입력 칸은 .claude-plugin/types/claude-code-tools 의 Skill · Artifact · Write · Edit · Bash 입력):
  // 1) Skill: skill 을 정규화(대소문자 · 앞뒤 공백 · 앞의 / 여러 개 무시, 이름공간 꼴은 마지막 토막)해 DRAWING_SKILLS 에 있을 때
  // 2) Artifact: action 이 없거나 publish 이고 asset 업로드가 아닌 게시 전부(files 맵만 있는 게시 · type_url 생성 포함) 3) Write · Edit: file_path 가 isVisualPath 4) Bash: runsFigureScript.
  // 대상 판정은 문자열 검사만 하고 대상일 때만 근거 상태를 읽는다(모든 Write · Edit · Bash 에 걸리므로). 사람 글 뒤 팝업 답(또는 AskUserQuestion 답)이 있어야 통과한다.
  // 근거 상태는 세션 단위 값($.state 는 «held by the host for the session», 주소에 에이전트 칸 없음)이라 메인이 답을 받은 뒤 부른 서브에이전트의 호출도 통과한다.
  // 서브에이전트(입력에 agentId 있음)는 사용자에게 물을 수 없으므로 따로 된 문구로 거부한다. 판정 중 오류가 나면 통과(fail-open)시켜 도구 호출 자체를 깨뜨리지 않는다.
  const drawTargets: Array<[string, (e: Record<string, unknown>) => boolean]> = [
    ['Skill', e => typeof e.skill === 'string' && DRAWING_SKILLS.includes((e.skill.toLowerCase().split(':').pop() ?? '').trim().replace(/^\/+/, ''))],
    ['Artifact', e => (e.action === undefined || e.action === 'publish') && e.asset !== true],
    ['Write', e => typeof e.file_path === 'string' && isVisualPath(e.file_path)],
    ['Edit', e => typeof e.file_path === 'string' && isVisualPath(e.file_path)],
    ['Bash', e => typeof e.command === 'string' && runsFigureScript(e.command)],
  ]
  for (const [tool, isTarget] of drawTargets) {
    on('tool.call', { tool }, async ($, e, next) => {
      try {
        if (isTarget(e as unknown as Record<string, unknown>) && !(await read($, answeredSinceHuman))) {
          const agentId = (e as { agentId?: unknown }).agentId
          return { deny: typeof agentId === 'string' && agentId !== '' ? SUBAGENT_FIGURE_DENY : FIGURE_DENY }
        }
      } catch {
        // fail-open
      }

      return next(e)
    })
  }

  on('command.run', { command: 'decision' }, async $ => {
    const req = await $.state.get(REQUEST_REF)
    if (!req.value) {
      return { text: '열려 있는 결정 팝업이 없습니다.' }
    }
    const opened = await $.ui.open({ id: PANE, title: `결정: ${req.value.title}`, focus: true, closeOnEscape: true, holdToasts: true, rows: wantedRows(req.value) })
    await update($, unplaced, () => !opened.isPlaced) // 다시 열어 놓이면 «팝업 안 보임» 예외도 끝난다(2026-10-27 qa 관찰)

    return { text: '결정 팝업을 다시 띄웠습니다.' }
  })

  // /mobile-mode [on|off|켜기|끄기]: 이 세션의 모바일 모드를 켜고 끈다(인자 없으면 뒤집기). 상태 파일도 같이 갱신한다. 모드를 바꾸는 유일한 길이다(사람 글로는 바뀌지 않는다).
  on('command.run', { command: 'mobile-mode' }, async ($, e) => {
    const next = mobileModeFromArg(String(e.args ?? ''), await read($, mobileMode))
    await update($, mobileMode, () => next)
    await writeMobileFile($, next)

    return { text: next ? '모바일 모드를 켰습니다.' : '모바일 모드를 껐습니다.' }
  })

  on('ui.close', async ($, e, next) => {
    if (e.id === PANE && e.origin.kind === 'person') {
      const req = await $.state.get(REQUEST_REF)
      if (req.value) {
        await update($, request, () => null)
        // 제목은 모델 글이라 한 줄로 만든다(가짜 «[결정 팝업 확인]» · «- » 줄 차단, security 2026-10-21).
        void $.prompt.submit({ text: `[결정 팝업 닫힘] ${oneLine(req.value.title)}: 사용자가 확정하지 않고 닫았습니다. 선택은 반영되지 않았습니다.` })
      }
    }

    return next(e)
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const el = $.ui.resolve(e)
    const { Box, Text, Button } = el
    // 모바일 화면 요소 표에는 Input 이 없다. 그 화면에서는 직접 입력 칸 대신 안내 한 줄을 그린다.
    const Input = 'Input' in el ? el.Input : undefined
    const req = await read($, request)
    const chosen = await read($, answers)
    const free = await read($, texts)
    const at = await read($, page)

    if (!req) {
      return <Text dimColor>열려 있는 결정이 없습니다.</Text>
    }

    let c = PALETTES.dark
    try {
      const row = (await $.config.list()).find(r => r.key === 'theme')
      if (row && typeof row.value === 'string' && row.value.startsWith('light')) c = PALETTES.light
    } catch {
      c = PALETTES.dark
    }

    // 표 행 사이 가로 구분선: Box 에는 한쪽 테두리 속성이 없어 높이 1 · 넘침 숨김 Box 에 «─» 한 줄을 잘라 그린다(Text wrap='truncate').
    const rule = (key: string) => (
      <Box key={key} height={1} overflow="hidden"><Text color={c.border} wrap="truncate">{'─'.repeat(240)}</Text></Box>
    )
    const n = req.items.length
    const goto = (p: number) => update($, page, () => Math.max(0, Math.min(n, p)))

    const it = at < n ? req.items[at] : undefined
    if (it) {
      const pick = chosen[it.id]

      return (
        <Box flexDirection="column">
          <Box flexDirection="row">
            <Text color={c.id} bold>{`${at + 1}/${n}  ${it.id}  `}</Text>
            <Text color={c.title} bold>{it.title}</Text>
          </Box>
          {paragraphs(it.problem).map((para, k) => (
            <Box key={`pa-${it.id}-${k}`} flexDirection="column">
              {k > 0 ? <Text> </Text> : null}
              <Text color={c.problem}>{para}</Text>
            </Box>
          ))}
          <Text> </Text>
          {it.options.map((o, k) => (
            <Box key={`o-${it.id}-${k}`} flexDirection="column">
              <Button
                key={`pick-${it.id}-${k}`}
                plain
                hotkey={String(k + 1)}
                variant={pick === k ? 'primary' : undefined}
                onPress={async () => {
                  await update($, answers, a => ({ ...a, [it.id]: k }))
                  await update($, texts, t => {
                    const { [it.id]: _drop, ...rest } = t

                    return rest
                  })
                  await goto(at + 1)
                }}
              >
                <Text color={pick === k ? c.picked : c.unpicked} bold>{pick === k ? '● ' : '○ '}</Text>
                <Text color={pick === k ? c.picked : c.label} bold={pick === k}>{o.label}</Text>
              </Button>
              {o.detail ? (
                <Box key={`d-${it.id}-${k}`} flexDirection="row">
                  <Text>{'   '}</Text>
                  <Box paddingX={1} backgroundColor={c.detailBg}>
                    <Text color={c.detailFg} backgroundColor={c.detailBg}>{o.detail}</Text>
                  </Box>
                </Box>
              ) : null}
            </Box>
          ))}
          <Box key={`free-row-${it.id}`} flexDirection="row">
            <Text color={pick === FREE ? c.picked : c.unpicked} bold>{pick === FREE ? '● ' : '○ '}</Text>
            {Input ? <Input
              key={`free-${it.id}`}
              label={`${it.options.length + 1}) 직접 입력: `}
              placeholder="글로 답하려면 ↓·Tab 으로 이 칸에 와서 적고 Enter"
              value={free[it.id] ?? ''}
              submitLabel="이 답으로"
              onSubmit={async (value: string) => {
                const text = value.trim()
                if (!text) return
                await update($, texts, t => ({ ...t, [it.id]: text }))
                await update($, answers, a => ({ ...a, [it.id]: FREE }))
                await goto(at + 1)
              }}
            /> : <Text color={c.detail}>{`${it.options.length + 1}) 직접 입력은 터미널·데스크톱 화면에서 쓸 수 있습니다`}</Text>}
          </Box>
          {it.options.some(o => o.pros || o.cons) ? (
            <Box key={`t-${it.id}`} flexDirection="column" borderStyle="single" borderColor={c.border}>
              <Box flexDirection="row">
                <Box width="30%" paddingX={1}><Text color={c.id} bold>선택지</Text></Box>
                <Box width="35%" paddingX={1}><Text color={c.pros} bold>장점</Text></Box>
                <Box width="35%" paddingX={1}><Text color={c.cons} bold>단점</Text></Box>
              </Box>
              {it.options.flatMap((o, k) => [
                rule(`tr-rule-${it.id}-${k}`),
                <Box key={`tr-${it.id}-${k}`} flexDirection="row">
                  <Box width="30%" paddingX={1}>
                    <Text color={pick === k ? c.picked : c.label} bold={pick === k}>{`${k + 1}) ${o.label}`}</Text>
                  </Box>
                  <Box width="35%" paddingX={1}><Text color={c.label}>{o.pros ?? '-'}</Text></Box>
                  <Box width="35%" paddingX={1}><Text color={c.label}>{o.cons ?? '-'}</Text></Box>
                </Box>,
              ])}
            </Box>
          ) : null}
          {it.terms && it.terms.length > 0 ? (
            <Box key={`tm-${it.id}`} flexDirection="column">
              <Text color={c.title} bold>용어</Text>
              <Box flexDirection="column" borderStyle="single" borderColor={c.border}>
                <Box flexDirection="row">
                  <Box width="30%" paddingX={1}><Text color={c.id} bold>용어</Text></Box>
                  <Box width="70%" paddingX={1}><Text color={c.id} bold>설명</Text></Box>
                </Box>
                {it.terms.flatMap((t, k) => [
                  rule(`tm-rule-${it.id}-${k}`),
                  <Box key={`tm-${it.id}-${k}`} flexDirection="row">
                    <Box width="30%" paddingX={1}><Text color={c.picked} bold>{t.term}</Text></Box>
                    <Box width="70%" paddingX={1}><Text color={c.label}>{t.meaning}</Text></Box>
                  </Box>,
                ])}
              </Box>
            </Box>
          ) : null}
          {it.experiments && it.experiments.length > 0 ? (
            <Box key={`xp-${it.id}`} flexDirection="column">
              <Text color={c.title} bold>실험 정리</Text>
              <Box flexDirection="column" borderStyle="single" borderColor={c.border}>
                <Box flexDirection="row">
                  <Box width="16%" paddingX={1}><Text color={c.id} bold>판</Text></Box>
                  <Box width="28%" paddingX={1}><Text color={c.id} bold>무엇을</Text></Box>
                  <Box width="28%" paddingX={1}><Text color={c.id} bold>어떻게</Text></Box>
                  <Box width="28%" paddingX={1}><Text color={c.id} bold>왜</Text></Box>
                </Box>
                {it.experiments.flatMap((x, k) => [
                  rule(`xr-rule-${it.id}-${k}`),
                  <Box key={`xr-${it.id}-${k}`} flexDirection="row">
                    <Box width="16%" paddingX={1}><Text color={c.picked} bold>{x.name}</Text></Box>
                    <Box width="28%" paddingX={1}><Text color={c.label}>{x.what}</Text></Box>
                    <Box width="28%" paddingX={1}><Text color={c.label}>{x.how}</Text></Box>
                    <Box width="28%" paddingX={1}><Text color={c.label}>{x.why}</Text></Box>
                  </Box>,
                ])}
              </Box>
            </Box>
          ) : null}
          <Box key={`sc-${it.id}`} flexDirection="column">
            <Text color={c.title} bold>예시(문제)</Text>
            {it.scenario ? <Text color={c.problem}>{it.scenario}</Text> : null}
          </Box>
          <Box key={`ex-${it.id}`} flexDirection="column">
            <Box flexDirection="row">
              <Text color={c.detail}>{'  └ '}</Text>
              <Text color={c.title} bold>선택지별 예시</Text>
            </Box>
            {it.options.map((o, k) => {
              // 줄 꼴은 «번호) 예시 글»(2026-10-21 사용자 지시: «1) (예시) 2) (예시) 이렇게»). 이름은 위 선택지·표에 이미 있어 되풀이하지 않는다.
              // 예시가 없는 요청(예시 필수 전 코드로 열린 요청)은 빈칸 대신 «(예시 없음)» 을 경고색으로 보인다.
              const ex = typeof o.example === 'string' ? o.example.trim() : ''

              return (
                <Box key={`ex-${it.id}-${k}`} flexDirection="row">
                  <Text>{'      '}</Text>
                  <Text color={pick === k ? c.picked : c.id} bold>{`${k + 1}) `}</Text>
                  <Text color={ex ? c.problem : c.missing}>{ex || '(예시 없음: 이 요청은 예시 없이 만들어졌습니다)'}</Text>
                </Box>
              )
            })}
          </Box>
          <Text> </Text>
          <Box flexDirection="row">
            <Button key="prev" plain hotkey="p" onPress={() => goto(at - 1)}>
              <Text color={c.nav}>← 이전</Text>
            </Button>
            <Text>   </Text>
            <Button key="next" plain hotkey="n" onPress={() => goto(at + 1)}>
              <Text color={c.nav}>다음 →</Text>
            </Button>
            <Text color={c.detail}>{`   (${Object.keys(chosen).length}/${n} 고름 · Esc 닫기)`}</Text>
          </Box>
        </Box>
      )
    }

    const missing = req.items.filter(it => pickedText(it, chosen[it.id], free[it.id]) === undefined)

    return (
      <Box flexDirection="column">
        <Box flexDirection="row">
          <Text color={c.id} bold>{'확인  '}</Text>
          <Text color={c.title} bold>{req.title}</Text>
        </Box>
        <Text> </Text>
        {req.items.map((it, i) => {
          const shown = pickedText(it, chosen[it.id], free[it.id])

          return (
            <Button key={`sum-${it.id}`} plain onPress={() => goto(i)}>
              <Text color={c.id} bold>{`${it.id} `}</Text>
              <Text color={c.label}>{`${it.title}: `}</Text>
              <Text color={shown === undefined ? c.missing : c.picked} bold>{shown ?? '(미선택)'}</Text>
            </Button>
          )
        })}
        <Text> </Text>
        {missing.length > 0 ? (
          <Text color={c.missing}>{`아직 고르지 않은 항목: ${missing.map(it => it.id).join(', ')} (항목을 눌러 이동)`}</Text>
        ) : (
          <Button
            key="confirm"
            plain
            hotkey="y"
            variant="primary"
            onPress={async () => {
              const text = answerText(req, chosen, free)
              await update($, request, () => null)
              // «잘못된 막힘» 표시는 답 메시지보다 먼저 쓴다: 메시지를 받은 모델이 곧바로 훅 수정을 시도할 때 표시가 이미 있어야 한다.
              // 요청을 비운 뒤라 이 사이에 들어온 새 팝업 호출은 새 요청으로 열리고 아래 «다시 읽기» 가 그 창을 지킨다. 실패해도 확정은 그대로 진행한다.
              if (req.items.some(it => pickedWrongBlock(it, chosen[it.id]))) await writeWrongBlockMarker($)
              await $.prompt.submit({ text })
              await update($, answeredSinceHuman, () => true)
              // 2026-11-11 실사고: 위 prompt.submit 을 기다리는 사이 모델이 팝업 도구를 다시 불러 새 요청이 떴다(열린 요청이 비어 있어 새 팝업으로 뜸).
              // 그 뒤에 실행된 이 ui.close 가 새 팝업의 창을 닫아 요청은 남았는데 창만 사라졌다(사용자가 /decision 을 쳐야 보임).
              // 그래서 닫기 직전에 요청을 다시 읽어 비어 있을 때만 닫고, 새 요청이 있으면 닫지 않고 그 제목 · 줄 수로 창을 다시 맞춘다.
              const now = await read($, request)
              if (!now) {
                await $.ui.close({ id: PANE })
              } else {
                const reopened = await $.ui.open({ id: PANE, title: `결정: ${now.title}`, focus: true, closeOnEscape: true, holdToasts: true, rows: wantedRows(now) })
                await update($, unplaced, () => !reopened.isPlaced)
              }
            }}
          >
            <Text color={c.picked} bold>이대로 확정</Text>
          </Button>
        )}
        <Box flexDirection="row">
          <Button key="back" plain hotkey="p" onPress={() => goto(n - 1)}>
            <Text color={c.nav}>← 이전</Text>
          </Button>
          <Text>   </Text>
          <Button key="restart" plain hotkey="r" onPress={() => goto(0)}>
            <Text color={c.nav}>처음부터 다시 보기</Text>
          </Button>
        </Box>
      </Box>
    )
  })
}
