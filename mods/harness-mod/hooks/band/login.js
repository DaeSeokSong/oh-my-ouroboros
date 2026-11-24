// Claude 로그인 만료 경보(intent/2026-11-16-login-expiry-band-warning.md). 순수 함수만 둔다(시험: tests/login.test.ts).
// 띠는 자격 증명 파일을 열지 않는다. scripts/login-expiry-export.sh 가 _usage/login-expiry 에 써 둔 만료 시각(ms) 숫자 한 줄만 읽는다.
// REF: knowledge/harness/code-history/mods__harness-mod__hooks__band__login.js.md
const DAY = 86400000
const KST = 9 * 3600000
const WARN_DAYS = 7

export function parseExpiry(text) {
  const s = typeof text === 'string' ? text.trim() : ''
  return /^[0-9]{12,14}$/.test(s) ? Number(s) : null
}

const p2 = n => String(n).padStart(2, '0')
function kst(ms) {
  const d = new Date(ms + KST)
  return `${p2(d.getUTCMonth() + 1)}-${p2(d.getUTCDate())} ${p2(d.getUTCHours())}:${p2(d.getUTCMinutes())}`
}

export function loginWarning(expiresAt, nowMs) {
  if (typeof expiresAt !== 'number' || !Number.isFinite(expiresAt) || typeof nowMs !== 'number') return null
  const left = expiresAt - nowMs
  if (left > WARN_DAYS * DAY) return null
  if (left <= 0) return { text: `⚠ 로그인 만료됨 (${kst(expiresAt)}) · claude auth login`, tone: 'loginR' }
  const n = Math.ceil(left / DAY)
  return { text: `⚠ 로그인 만료 D-${n} (${kst(expiresAt)}) · claude auth login`, tone: n >= 4 ? 'loginY' : n >= 2 ? 'loginO' : 'loginR' }
}
