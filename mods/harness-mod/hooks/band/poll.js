// 폴링 판단 순수 함수(register.js 가 쓴다, 시험: tests/band.test.ts). 시계는 인자로 받는다.
const FRESH_S = 15 // 서버 캐시가 이 이하면 다시 채우지 않는다
const STALE_S = 60 // 캐시 ts 가 지금보다 이만큼 넘게 오래됐거나 미래면 버린다(낡은 값을 «현재» 로 보이지 않게)

// 띠가 그려지는 면(terminal·desktop)이 확실히 없을 때만 false. 예외·알 수 없는 모양·빈 목록은 true(영구 «조회 실패» 방지).
export function wantsBand(surfaces) {
  if (!Array.isArray(surfaces) || !surfaces.length) return true
  const kinds = surfaces.map(s => (typeof s === 'string' ? s : s && typeof s.kind === 'string' ? s.kind : null))
  if (kinds.some(k => k === null)) return true
  return kinds.some(k => k === 'terminal' || k === 'desktop')
}

// 캐시 ts 가 60초 넘게 오래됐거나 미래면 null.
export function validCache(cached, nowMs) {
  if (!cached || typeof cached !== 'object' || typeof cached.ts !== 'number' || !Number.isFinite(cached.ts)) return null
  const age = nowMs / 1000 - cached.ts
  return age > STALE_S || age < -STALE_S ? null : cached
}

// 수집기를 부를지: 유효 캐시가 15초를 넘었거나 없고, 마지막 시도(server.attempt)도 15초 안이 아닐 때만.
export function needsCollect(cached, attempt, nowMs) {
  const now = nowMs / 1000
  const fresh = cached && now - cached.ts <= FRESH_S
  const tried = attempt && typeof attempt.ts === 'number' && Number.isFinite(attempt.ts) && now - attempt.ts <= FRESH_S && now - attempt.ts >= -5
  return !fresh && !tried
}
