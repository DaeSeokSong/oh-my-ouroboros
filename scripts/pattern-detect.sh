#!/usr/bin/env bash
# 반복 패턴 1차 후보 추출 — prompts.jsonl 정규화 + 빈도 카운트.
#
# 목적: 자가진화 감지의 "빈도층"(결정론적, 토큰 0). 표면이 같거나 유사한
#       프롬프트의 반복 횟수를 센다. 표면이 다른 같은 의도(예: "토큰 점검" vs
#       "토큰 효율 봐줘")는 여기서 못 묶으므로, 이 출력을 learn-from-feedback이
#       LLM 의미 클러스터링으로 2차 묶음 → mem0 T40에 영속한다.
#
# 사용:  bash pattern-detect.sh [최소반복횟수=3] [최근N일=14]
# 출력:  "<횟수>  <정규화 키프레이즈>"  (반복 ≥ 최소횟수만)
set -uo pipefail

EVOLVE_DIR="$HOME/.claude/_evolve"
LOG="$EVOLVE_DIR/prompts.jsonl"
MIN="${1:-3}"
DAYS="${2:-14}"

[ -f "$LOG" ] || { echo "(로그 없음 — UserPromptSubmit hook 등록 후 수집됩니다)"; exit 0; }
command -v jq >/dev/null 2>&1 || { echo "ERROR: jq 필요" >&2; exit 2; }

# 최근 N일 컷오프(가능하면). date 연산 실패 시 전체 사용.
CUTOFF=$(date -u -d "-${DAYS} days" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo "")

# 1) 기간 필터 → prompt 추출
#    2) 정규화: 소문자화, 구두점·숫자 제거, 한글 기능어(조사·군말) 약화, 공백 정리
#    3) 너무 짧은 줄 제외 → 빈도 카운트 → 최소횟수 이상만
if [ -n "$CUTOFF" ]; then
  # 관용 파싱 (2026-07-18 Codex): 손상된 JSONL 한 줄이 jq 전체를 중단시켜 부분 결과를 성공
  # 처리하던 것 방지 — -R로 줄 단위, fromjson?로 불량 줄만 건너뜀.
  FILTER=$(jq -rR --arg c "$CUTOFF" 'fromjson? | select(.ts >= $c) | .prompt // empty' "$LOG" 2>/dev/null)
else
  FILTER=$(jq -rR 'fromjson? | .prompt // empty' "$LOG" 2>/dev/null)
fi

printf '%s\n' "$FILTER" \
  | tr 'A-Z' 'a-z' \
  | sed -E 's/[[:punct:]]+/ /g; s/[0-9]+/ /g' \
  | sed -E 's/(해줘|해주세요|해|하자|하고|진행|좀|그리고|이를|이거|그거|그건|줄래|줘)/ /g' \
  | sed -E 's/  +/ /g; s/^ +//; s/ +$//' \
  | awk 'length($0) > 4' \
  | sort | uniq -c | sort -rn \
  | awk -v m="$MIN" '$1 >= m { print }' \
  | head -5 | LC_ALL=C.utf8 grep -oE '^.{1,88}'
# 상위 5건·줄당 88자(횟수 7자+키프레이즈 ~80자) 캡 — T40 판정에는 빈도+앞부분이면 충분.
# 절단 도구 선정 실측(2026-07-23): cut -c/mawk substr=바이트 단위(한글 중간 깨짐), GNU sed는
# 멀티바이트 .{N} 미동작, gawk 부재 → UTF-8 로케일 grep -oE만 문자 단위 절단 성공.
# 무캡 시 ~2KB가 세션 시작·compact마다 통째 주입되던 낭비 제거 (2026-07-23 토큰 점검).

# 사용 마커 — harness-usage-check.sh가 자가진화 루프 정지(PATTERNS_UNMINED)를 감지하는 기준점
mkdir -p "$HOME/.claude/_usage" 2>/dev/null && touch "$HOME/.claude/_usage/pattern-detect-last" 2>/dev/null

exit 0
