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
# REF: knowledge/harness/code-history/scripts__pattern-detect.sh.md

EVOLVE_DIR="$HOME/.claude/_evolve"
LOG="$EVOLVE_DIR/prompts.jsonl"
MIN="${1:-3}"
DAYS="${2:-14}"

# WHY: stdout 은 SessionStart 후보 머리말 아래에 그대로 실리는 자리라 안내문이 섞이면 «후보 0건»과 «로그 없음»이
# 한 덩어리로 읽힌다(09-14 재감사 §3).
[ -f "$LOG" ] || { echo "(로그 없음 — UserPromptSubmit hook 등록 후 수집됩니다)" >&2; exit 0; }
command -v jq >/dev/null 2>&1 || { echo "ERROR: jq 필요" >&2; exit 2; }

CUTOFF=$(date -u -d "-${DAYS} days" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo "")

# WHY: 자동 예약 · 측정 러너 회차 · 훅 알림은 사람의 반복 요청이 아니다(2026-11-12, T40 미판정 3건이 전부 이것).
# 로그 자체는 APPROVED 인용 대조에 쓰여 prompt-log.sh 는 고치지 않고 세는 쪽에서만 뺀다.
MACHINE_RX='^\s*(\[예약 점검|\[측정 회차|effort-eval (측정|시험) 회차|\[하네스 변경 알림)'
if [ -n "$CUTOFF" ]; then
  # WHY: 손상된 JSONL 한 줄이 jq 전체를 중단시켜 부분 결과를 성공 처리했다(2026-07-18 Codex).
  FILTER=$(jq -rR --arg c "$CUTOFF" --arg m "$MACHINE_RX" 'fromjson? | select(.ts >= $c) | (.prompt // empty) | select(test($m) | not) | .[0:200]' "$LOG" 2>/dev/null)
else
  FILTER=$(jq -rR --arg m "$MACHINE_RX" 'fromjson? | (.prompt // empty) | select(test($m) | not) | .[0:200]' "$LOG" 2>/dev/null)
fi
# WHY: prompt-log 보관 길이가 200→2000 자로 늘었어도 빈도 키는 앞 200자 그대로 둔다. 키가 길어지면 같은 요청의 꼬리 차이로 묶음이 쪼개진다.

OUT=$(printf '%s\n' "$FILTER" \
  | tr '[:upper:]' '[:lower:]' \
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
# WHY: 무캡 시 ~2KB 가 세션 시작·compact 마다 통째 주입됐다(2026-07-23 토큰 점검). 그래서 상위 5건·줄당 88자로 자른다.
# NEVER: grep -oE 로 자르지 않는다. grep(3.7)의 `.` 는 U+D558 이상(«하»·«한»·«해»)을 못 맞혀 줄이 사라지거나 잘렸다(2026-09-14 교정).

# WHY: 모델 의무 문장으로는 T40 후보 대장 기록이 8일간 0건이었다(09-14 감사 §2-3). 감지와 같은 실행 안에서 훅이 직접 적는다.
# NEVER: 여기서 대장을 직접 cp→mv 하지 않는다. 동시 실행에서 서로를 덮어써 행을 잃었다(09-14 재감사 B1). 쓰기는 candidates-append.sh 한 곳이다.
if [ -n "$OUT" ]; then
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    CNT=$(printf '%s' "$line" | awk '{print $1}')
    TEXT=$(printf '%s' "$line" | sed -E 's/^[[:space:]]*[0-9]+[[:space:]]+//; s/[[:space:]]+$//')
    [ -n "$TEXT" ] || continue
    # NEVER: stderr 를 버리지 않는다. 헬퍼 실패가 «조용히 안 적힘»이 된다.
    bash "$HOME/.claude/scripts/candidates-append.sh" T40 "$TEXT ×$CNT" >/dev/null
  done <<EOF
$OUT
EOF
fi

# WHY: scripts/harness-usage-check.sh 가 이 마커로 자가진화 루프 정지(PATTERNS_UNMINED)를 감지한다.
mkdir -p "$HOME/.claude/_usage" 2>/dev/null && touch "$HOME/.claude/_usage/pattern-detect-last" 2>/dev/null

exit 0
