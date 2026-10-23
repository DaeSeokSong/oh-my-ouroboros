// 화면 표시용 가림(순수 함수). 어시스턴트 응답·도구 출력의 이메일·JWT·API 토큰·긴 Base64 를 «… 가림» 표시로 바꾼다.
// 가림은 화면 전용이다: 모델이 읽는 원문·대화 기록·외부 전송에는 원문이 그대로 남는다(보안 장치가 아니라 화면 공유용, intent 2026-10-23 4절).
// 오탐보다 놓침을 줄이는 쪽이지만, 커밋 해시(16진수만)·URL·경로 조각·일반 영문은 건드리지 않는다. 코드 블록 안도 가린다.

const NOT_ALNUM_BEFORE = '(?<![A-Za-z0-9])'

// 순서가 중요하다: JWT → API 토큰 → 이메일 → Base64(앞의 것이 이미 «…가림» 으로 바뀐 뒤라 긴 Base64 가 중복으로 잡히지 않는다).
// 성능 근거(검수 2026-10-23): 반복 글자 집합 앞에는 «앞 경계» 뒷봄(lookbehind)을 둬서 시작 위치를 낱말 덩어리의 첫 글자로만 한정한다.
//   없으면 공백 없는 긴 한 줄(base64 -w0 · data URI)에서 시작 위치마다 끝까지 훑어 n² 이 된다(렌더 훅이 멈추면 mod 전체가 멈춘다).
const JWT = /(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g
// sk-ant- 는 sk- 에 포함된다. 앞이 영숫자면(disk-… · task-…) 낱말 속 우연이라 건너뛴다.
// Atlassian ATATT · GitHub gh[opsur]_ · GitLab glpat- · Google AIza · HuggingFace hf_ 도 토큰 꼴이다.
const TOKEN = new RegExp(
  `${NOT_ALNUM_BEFORE}(?:sk-|gh[opsur]_|github_pat_|glpat-|xox[bap]-|tvly-)[A-Za-z0-9_-]{8,}`
  + `|${NOT_ALNUM_BEFORE}ATATT[A-Za-z0-9_=-]{20,}`
  + `|${NOT_ALNUM_BEFORE}AIza[A-Za-z0-9_-]{30,}`
  + `|${NOT_ALNUM_BEFORE}hf_[A-Za-z]{30,}`
  + `|${NOT_ALNUM_BEFORE}AKIA[0-9A-Z]{16}(?![A-Za-z0-9])`, 'g')
// 끝 라벨은 영문자만(react@18.2.0 같은 패키지 버전은 이메일이 아니다). 앞 경계가 있어 로컬부 길이 상한은 두지 않는다
// (상한을 두면 긴 로컬부 이메일이 통째로 안 가려진다). 도메인은 라벨 수·길이만 제한한다.
const EMAIL = /(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@(?:[A-Za-z0-9-]{1,63}\.){1,10}[A-Za-z]{2,24}/g
// URL-safe Base64(_ -) 도 같은 집합에 넣는다. 경로·낱말 오탐은 isSecretLike 가 거른다.
const BASE64 = /(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+/_-]{40,}={0,2}(?![A-Za-z0-9+/=_-])/g
const HEX_ONLY = /^[0-9a-fA-F]+$/
const WINDOW = 200 // Base64 후보 둘레의 «낱말» 경계를 찾는 최대 거리(공백 없는 긴 줄에서 후보마다 끝까지 훑지 않는다)
const MAX_TEXT = 200000 // 가림 대상 글자 수 상한: 넘으면 앞부분만 가리고 나머지는 화면에서 잘라 보이지 않게 한다
const CUT_NOTE = '\n«(이하 생략: 가림 대상 초과)»'

// 긴 Base64 후보가 진짜 비밀 꼴인지: 대소문자·숫자가 모두 섞여야 하고, 16진수만이면(커밋 해시) 아니며,
// URL(://)·경로(앞이 / ~ .)·슬래시로 끊긴 짧은 낱말 줄(경로 조각)이면 아니다.
function isSecretLike(run, before, word) {
  if (HEX_ONLY.test(run) || !/[a-z]/.test(run) || !/[A-Z]/.test(run) || !/[0-9]/.test(run)) return false
  if (word.includes('://') || /[/~.]$/.test(before)) return false
  const segs = run.split('/')
  if (segs.length <= 3) return true
  for (const s of segs) if (s.length >= 24) return true // 스프레드(Math.max(...)) 는 조각이 아주 많으면 호출 스택을 넘는다
  return false
}

/** 텍스트의 비밀 꼴을 가린다. { text, count }: 바뀐 곳이 없으면 같은 문자열과 0 을 돌려준다. */
export function maskText(text) {
  if (typeof text !== 'string' || text.length < 8) return { text, count: 0 }
  let count = 0
  const tooLong = text.length > MAX_TEXT
  if (tooLong) { text = text.slice(0, MAX_TEXT); count++ } // 원문을 그대로 보이면 가림이 새므로 «잘라서 가림»
  const sub = (re, label) => { text = text.replace(re, () => { count++; return label }) }
  sub(JWT, '«JWT 가림»')
  sub(TOKEN, '«토큰 가림»')
  sub(EMAIL, '«이메일 가림»')
  text = text.replace(BASE64, (run, offset, whole) => {
    let from = offset // 후보가 든 «낱말» 의 시작·끝: 공백·줄바꿈까지, 최대 WINDOW 자
    while (from > 0 && offset - from < WINDOW && whole[from - 1] !== ' ' && whole[from - 1] !== '\n') from--
    let end = offset + run.length
    const lim = Math.min(whole.length, end + WINDOW)
    while (end < lim && !/\s/.test(whole[end])) end++
    if (!isSecretLike(run, whole.slice(Math.max(0, offset - 1), offset), whole.slice(from, end))) return run
    count++
    return '«Base64 가림»'
  })
  return { text: tooLong ? text + CUT_NOTE : text, count }
}

/** 도구 결과 output 안의 글 칸(string 자체 · stdout · stderr · content · file.content)만 가린다. 구조는 그대로 두고 값만 바꿔 도구별 스키마 검증을 깨지 않는다. */
export function maskOutput(output) {
  const one = s => (typeof s === 'string' ? maskText(s) : { text: s, count: 0 })
  if (typeof output === 'string') return one(output).text
  if (output === null || typeof output !== 'object' || Array.isArray(output)) return output
  let changed = false
  const next = { ...output }
  for (const k of ['stdout', 'stderr', 'content']) {
    const r = one(next[k])
    if (r.count) { next[k] = r.text; changed = true }
  }
  if (next.file !== null && typeof next.file === 'object' && !Array.isArray(next.file)) {
    const r = one(next.file.content)
    if (r.count) { next.file = { ...next.file, content: r.text }; changed = true }
  }
  return changed ? next : output
}
