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

# 부재 안내는 stderr 로 — stdout 은 SessionStart 후보 머리말 아래에 그대로 실리는 자리라
# 안내문이 섞이면 «후보 0건»과 «로그 없음»이 한 덩어리로 읽힌다 (09-14 재감사 §3).
[ -f "$LOG" ] || { echo "(로그 없음 — UserPromptSubmit hook 등록 후 수집됩니다)" >&2; exit 0; }
command -v jq >/dev/null 2>&1 || { echo "ERROR: jq 필요" >&2; exit 2; }

# 최근 N일 컷오프(가능하면). date 연산 실패 시 전체 사용.
CUTOFF=$(date -u -d "-${DAYS} days" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo "")

# 1) 기간 필터 → prompt 추출
#    2) 정규화: 소문자화, 구두점·숫자 제거, 한글 기능어(조사·군말) 약화, 공백 정리
#    3) 너무 짧은 줄 제외 → 빈도 카운트 → 최소횟수 이상만
if [ -n "$CUTOFF" ]; then
  # 관용 파싱 (2026-07-18 Codex): 손상된 JSONL 한 줄이 jq 전체를 중단시켜 부분 결과를 성공
  # 처리하던 것 방지 — -R로 줄 단위, fromjson?로 불량 줄만 건너뜀.
  FILTER=$(jq -rR --arg c "$CUTOFF" 'fromjson? | select(.ts >= $c) | (.prompt // empty)[0:200]' "$LOG" 2>/dev/null)
else
  FILTER=$(jq -rR 'fromjson? | (.prompt // empty)[0:200]' "$LOG" 2>/dev/null)
fi
# [0:200] — prompt-log 보관 길이가 200→2000 자로 늘었어도(APPROVED 인용 검사·T12 탐지가 뒤 문장을
# 봐야 해서) **빈도 키는 앞 200자 그대로** 둔다. 키가 길어지면 같은 요청의 꼬리 차이로 묶음이 쪼개진다.

OUT=$(printf '%s\n' "$FILTER" \
  | tr 'A-Z' 'a-z' \
  | sed -E 's/[[:punct:]]+/ /g; s/[0-9]+/ /g' \
  | awk '{ # 기능어는 낱말(공백 토큰) 끝의 어미이거나 토큰 전체일 때만 지운다 — 낱말 속 «해결»의 «해» 까지 지우던 결함(2026-10-01 감사 P6)
        n = split($0, w, " "); o = ""
        for (i = 1; i <= n; i++) {
          t = w[i]
          if (t ~ /(해주세요|해줘|하자|하고|줄래|줘|해)$/) sub(/(해주세요|해줘|하자|하고|줄래|줘|해)$/, "", t)
          if (t == "" || t == "진행" || t == "좀" || t == "그리고" || t == "이를" || t == "이거" || t == "그거" || t == "그건") continue
          o = o " " t
        }
        print o }' \
  | sed -E 's/  +/ /g; s/^ +//; s/ +$//' \
  | awk 'length($0) > 4' \
  | sort | uniq -c | sort -rn \
  | awk -v m="$MIN" '$1 >= m { print }' \
  | head -5 \
  | { python3 -c 'import sys;[sys.stdout.write(l.rstrip("\n")[:88]+"\n") for l in sys.stdin]' 2>/dev/null \
      || cut -c1-88; })
[ -n "$OUT" ] && printf '%s\n' "$OUT"
# 상위 5건·줄당 88자(횟수 7자+키프레이즈 ~80자) 캡 — T40 판정에는 빈도+앞부분이면 충분.
# 절단 도구 선정 실측(2026-07-23): cut -c/mawk substr=바이트 단위(한글 중간 깨짐), GNU sed는
# 멀티바이트 .{N} 미동작, gawk 부재 → 당시엔 UTF-8 로케일 grep -oE 로 갔다.
# 2026-09-14 교정: 그 grep(3.7)은 로케일과 무관하게 `.` 가 U+D558 이상(ㅎ 계열 «하»·«한»·«해»)을
# 못 맞힌다. 키프레이즈가 그 글자로 시작하면 줄이 통째로 사라지고, 중간에 있으면 거기서 잘렸다.
# prompt-log.sh 와 같은 폴백(python3 문자 절단 → 부재 시 cut)으로 되돌린다.
# 무캡 시 ~2KB가 세션 시작·compact마다 통째 주입되던 낭비 제거 (2026-07-23 토큰 점검).

# T40 후보 대장 기록 (2026-09-14 신설)
# 왜: 감지층(위 출력)과 저장소가 끊겨 있어 하류 전체(승인 큐·7일 판정·bench 복귀)가 도달 불가였다
#     — 09-14 감사 §2-3 «대장은 09-06 생성 후 헤더 1줄에서 무변». 모델 의무 문장으로는 8일간 0건이었으므로
#     감지와 같은 실행 안에서 훅이 직접 적는다. 세션마다 같은 패턴이 재검출되므로 요약 중복은 건너뛴다.
# 쓰기는 candidates-append.sh 한 곳으로 — 여기서 직접 cp→mv 하던 판은 동시 실행에서 서로를
# 덮어써 행을 잃었다(09-14 재감사 B1). 중복 차단·id 연번·헤더 보장도 그 잠금 안에서 한다.
if [ -n "$OUT" ]; then
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    CNT=$(printf '%s' "$line" | awk '{print $1}')
    TEXT=$(printf '%s' "$line" | sed -E 's/^[[:space:]]*[0-9]+[[:space:]]+//; s/[[:space:]]+$//')
    [ -n "$TEXT" ] || continue
    # stdout 만 버린다 — 헬퍼 실패(stderr)는 그대로 흘려 «조용히 안 적힘»을 막는다.
    bash "$HOME/.claude/scripts/candidates-append.sh" T40 "$TEXT ×$CNT" >/dev/null
  done <<EOF
$OUT
EOF
fi

# 사용 마커 — harness-usage-check.sh가 자가진화 루프 정지(PATTERNS_UNMINED)를 감지하는 기준점
mkdir -p "$HOME/.claude/_usage" 2>/dev/null && touch "$HOME/.claude/_usage/pattern-detect-last" 2>/dev/null

exit 0
