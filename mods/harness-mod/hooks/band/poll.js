// 폴링 판단 순수 함수(register.js 가 쓴다, 시험: tests/band.test.ts). 시계는 인자로 받는다.
// REF: knowledge/harness/code-history/mods__harness-mod__hooks__band__poll.js.md
const FRESH_S = 15
const STALE_S = 60

export function wantsBand(surfaces) {
  if (!Array.isArray(surfaces) || !surfaces.length) return true
  const kinds = surfaces.map(s => (typeof s === 'string' ? s : s && typeof s.kind === 'string' ? s.kind : null))
  if (kinds.some(k => k === null)) return true
  return kinds.some(k => k === 'terminal' || k === 'desktop')
}

export function validCache(cached, nowMs) {
  if (!cached || typeof cached !== 'object' || typeof cached.ts !== 'number' || !Number.isFinite(cached.ts)) return null
  const age = nowMs / 1000 - cached.ts
  return age > STALE_S || age < -STALE_S ? null : cached
}

export function needsCollect(cached, attempt, nowMs) {
  const now = nowMs / 1000
  const fresh = cached && now - cached.ts <= FRESH_S
  const tried = attempt && typeof attempt.ts === 'number' && Number.isFinite(attempt.ts) && now - attempt.ts <= FRESH_S && now - attempt.ts >= -5
  return !fresh && !tried
}
