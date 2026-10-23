// 하네스 변경 전파의 받는 쪽(intent/2026-10-21-harness-change-propagation-gate.md 개정 1). 순수 함수만 둔다(시험: tests/band.test.ts).
// 커밋 훅(scripts/propagate-queue.sh enqueue)이 _usage/propagate/pending.jsonl 에 커밋을 적으면, 각 세션의 이 mod 가 3초마다 읽어
// 자기 세션에 알림을 넣고 _usage/propagate/ack/<세션 id> 에 «해시 TAB 시각 TAB 방식» 을 남긴다. 커밋한 세션의 턴 종료 훅
// (scripts/propagate-gate.sh)이 그 기록으로 전달 여부를 판정한다.
// 방식: mod(알림을 넣음) · self(이 세션이 만든 커밋이라 알리지 않음) · baseline(이 세션이 뜨기 전 커밋이라 쏟아 넣지 않음).
// 같은 피드백 대조 고리 Q1(훅이 대장에 쓴 새 후보를 매니저 세션이 받음)도 이 파일의 읽기·받음 기록 부분을 같이 쓴다(intent G2).

const HASH_RE = /^[0-9a-f]{7,40}$/
const SID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
const KEEP = 500

// 제어·양방향 제어 글자와 보이지 않는 글자(폭 없는 문자 U+200B~200F · U+2060~2064 · BOM U+FEFF · 태그 문자 U+E0000~E007F)를 지운다.
// 대기 파일은 커밋 제목에서 오고 알림은 세션 입력 자리로 들어가므로 신뢰하지 않는다(보이지 않는 지시 숨김 차단, security 검수 2026-10-21).
const stripped = c => c < 0x20 || (c >= 0x7f && c <= 0x9f) || c === 0x2028 || c === 0x2029 ||
  (c >= 0x202a && c <= 0x202e) || (c >= 0x2066 && c <= 0x2069) || (c >= 0x200b && c <= 0x200f) ||
  (c >= 0x2060 && c <= 0x2064) || c === 0xfeff || (c >= 0xe0000 && c <= 0xe007f)
function clean(s, max = 160) {
  let out = ''
  for (const ch of String(s)) {
    if (stripped(ch.codePointAt(0))) continue
    if (out.length >= max) break
    out += ch
  }
  return out
}

// pending.jsonl 한 줄씩: 형식이 맞는 줄만 { ts, hash, subject, author } 로. 깨진 줄은 버린다.
export function parsePending(text) {
  const out = []
  for (const line of String(text || '').split('\n')) {
    if (!line.trim()) continue
    let o
    try { o = JSON.parse(line) } catch { continue }
    if (!o || typeof o !== 'object' || typeof o.hash !== 'string' || !HASH_RE.test(o.hash)) continue
    if (typeof o.ts !== 'number' || !Number.isFinite(o.ts)) continue
    out.push({ ts: o.ts, hash: o.hash, subject: typeof o.subject === 'string' ? clean(o.subject) : '',
      author: typeof o.author === 'string' && SID_RE.test(o.author) ? o.author : '' })
  }
  return out
}

// ack 파일에서 받은 해시 집합.
export function ackedSet(text) {
  return new Set(String(text || '').split('\n').map(l => l.split('\t')[0]).filter(h => HASH_RE.test(h)))
}

// 받지 않은 줄을 셋으로 가른다. self: 이 세션이 만든 커밋, baseline: 이 세션이 뜨기 전(startTs) 커밋, deliver: 알림을 넣을 커밋.
export function plan(entries, acked, selfSid, startTs) {
  const out = { deliver: [], self: [], baseline: [] }
  const seen = new Set()
  for (const e of entries) {
    if (acked.has(e.hash) || seen.has(e.hash)) continue
    seen.add(e.hash)
    if (selfSid && e.author === selfSid) out.self.push(e)
    else if (e.ts < startTs) out.baseline.push(e)
    else out.deliver.push(e)
  }
  return out
}

// 세션에 넣을 알림 한 덩어리. 받은 세션은 반영만 하고 회신·사용자 보고를 하지 않는다(rules-lazy/peer-session-messages.md).
export function noticeText(entries) {
  const lines = entries.map(e => `- ${e.hash} ${e.subject}`)
  return ['[하네스 변경 알림 · 회신 불요] 하네스 저장소에 새 커밋이 생겼습니다.', ...lines,
    '필요하면 바뀐 규칙·스킬 파일을 다시 읽어 반영만 하십시오. 회신하거나 사용자에게 따로 보고하지 마십시오.'].join('\n')
}

// ack 파일의 새 내용: 앞 내용에 «해시 TAB 시각 TAB 방식» 줄을 더하고 마지막 500줄만 남긴다.
export function ackText(prev, groups, now) {
  const add = []
  for (const [mode, list] of groups) for (const e of list) add.push(`${e.hash}\t${now}\t${mode}`)
  const lines = String(prev || '').split('\n').filter(Boolean).concat(add)
  return lines.slice(-KEEP).join('\n') + '\n'
}

export const isSessionId = s => typeof s === 'string' && SID_RE.test(s)
