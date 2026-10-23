#!/usr/bin/env bash
# Claude Code StatusLine — minimal (모델 + ctx % + progress bar)
# ⚠️ 현재 기본 배선 아님: settings.json statusLine은 claudenews HUD 사용 중.
#    ctx % 상시 표시가 필요한 머신에서만 statusLine 필드를 이 스크립트로 교체
#    (상세: rules-lazy/context-management.md § 실시간 추적 수단)
# 출력: 🤖 Opus | 🧠 25% 🟢 [██░░░░░░░░]
# 의존: jq (없으면 fallback default 값)
# ccusage 의존 ❌ — 모든 서버에서 동일 동작
set -uo pipefail

INPUT=$(cat)

PCT=$(printf '%s' "$INPUT" | jq -r '.context_window.used_percentage // 0' 2>/dev/null | cut -d. -f1)
PCT=${PCT:-0}
# 비정수(음수·문자열·null 등)는 0 으로 — 아래 산술·비교에 그대로 들어가면 스테이터스라인이 깨진다
case "$PCT" in ''|*[!0-9]*) PCT=0 ;; esac
MODEL=$(printf '%s' "$INPUT" | jq -r '.model.display_name // "Claude"' 2>/dev/null)
[ -z "$MODEL" ] && MODEL="Claude"

# 임계값 이모지
if [ "$PCT" -ge 80 ]; then WARN="🔴"
elif [ "$PCT" -ge 60 ]; then WARN="🟡"
else WARN="🟢"
fi

# 10단계 progress bar
FILLED=$((PCT / 10))
[ "$FILLED" -gt 10 ] && FILLED=10
EMPTY=$((10 - FILLED))
BAR=""
i=0; while [ "$i" -lt "$FILLED" ]; do BAR="${BAR}█"; i=$((i+1)); done
i=0; while [ "$i" -lt "$EMPTY" ]; do BAR="${BAR}░"; i=$((i+1)); done

printf '🤖 %s | 🧠 %s%% %s [%s]\n' "$MODEL" "$PCT" "$WARN" "$BAR"
