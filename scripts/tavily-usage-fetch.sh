#!/usr/bin/env bash
# Tavily 사용량 캐시 갱신기 — /usage(비과금: 검색 크레딧 안 깎임) 조회 → 캐시에 "used limit" 1줄 기록.
# coralline seg_tavily가 캐시가 TTL을 넘으면 백그라운드로 호출. flock(부재 시 mkdir 대체 락)으로 동시 실행 1개만 보장.
# API 키는 mcp-secrets.env(gitignore, 600)에서만 읽음 — 평문 노출 없음.
set -euo pipefail

CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/coralline"
mkdir -p "$CACHE_DIR"
CACHE="$CACHE_DIR/tavily-usage"

# 동시 실행 방지 (이미 갱신 중이면 조용히 종료)
if command -v flock >/dev/null 2>&1; then
    exec 9>"$CACHE_DIR/tavily-usage.lock" 2>/dev/null || exit 0
    flock -n 9 || exit 0
else
    # flock 부재 시 mkdir 원자성 기반 대체 락 — 가드 없이 진행하지 않는다.
    # 비정상 종료(kill -9 등)로 남은 stale 락은 2분 초과 시 회수
    # (정상 실행은 curl --max-time 10 이내 종료하므로 2분이면 충분히 보수적).
    LOCK_D="$CACHE_DIR/tavily-usage.lock.d"
    if ! mkdir "$LOCK_D" 2>/dev/null; then
        [ -n "$(find "$LOCK_D" -maxdepth 0 -mmin +2 2>/dev/null)" ] || exit 0
        rmdir "$LOCK_D" 2>/dev/null || true
        mkdir "$LOCK_D" 2>/dev/null || exit 0
    fi
    trap 'rmdir "$LOCK_D" 2>/dev/null || true' EXIT
fi

# 실패(429 rate-limit·스키마 변경 등) 시에도 캐시 mtime을 advance시켜,
# statusline이 매 렌더마다 재시도(amplification)하여 /usage를 두드리는 것을 막는다 — backoff.
# 성공 시에는 아래 mv가 mtime을 다시 갱신하므로 무해.
touch "$CACHE" 2>/dev/null || true

SECRETS="$HOME/.claude/mcp-secrets.env"
[ -f "$SECRETS" ] && { set -a; . "$SECRETS"; set +a; }
[ -n "${TAVILY_API_KEY:-}" ] || exit 0

resp="$(curl -s --max-time 10 -H "Authorization: Bearer $TAVILY_API_KEY" https://api.tavily.com/usage)" || exit 0
out="$(printf '%s' "$resp" | python3 -c '
import json, sys
try:
    a = json.load(sys.stdin).get("account", {})
    u = a.get("plan_usage"); l = a.get("plan_limit") or 0
    print(f"{u} {l}" if u is not None else "")
except Exception:
    print("")
' 2>/dev/null)"
[ -n "$out" ] || exit 0
printf '%s\n' "$out" > "$CACHE.tmp" && mv "$CACHE.tmp" "$CACHE"
