#!/usr/bin/env bash
# skill-usage-log.sh — Skill 도구 호출을 1줄씩 기록한다 (PreToolUse, matcher `Skill`).
#   intent/2026-11-24-harness-review-six-items.md W10 성공 기준 1. 보고: scripts/skill_usage_report.py
# 기록: ~/.claude/_usage/skill-usage.tsv — 열 time · session(8자) · skill · caller. 인자(tool_input.args)와 본문은 남기지 않는다.
#   skill 은 [A-Za-z0-9_.:-] 만 허용한다(플러그인 꼴 plugin:skill 유지). 허용 밖 글자가 하나라도 있으면 일부만 남겨 다른
#   이름과 합쳐지지 않도록 기록하지 않는다(살균 전후 문자열이 다르면 버림). 80자를 넘으면 앞 80자만 기록한다. caller 는 agent_type 이 있으면 그 값, 없으면 main.
#   파일 모드 600, 머리줄은 새로 만들 때만, 2MB 를 넘으면 뒤쪽 절반만 남긴다(flock 아래, 임시 파일 → mv).
#   기록 파일 · 폴더 · 잠금 파일이 심볼릭 링크이면 쓰지 않는다. 어떤 실패든 조용히 exit 0(스킬 호출을 막지 않는다, 출력 없음).
#   무결성: agent-spawn-log.sh 와 같이 신뢰 경계 밖의 사용 현황 기록이다(위조 불가 증거 아님).
MAX=2097152
HEADER=$'time\tsession\tskill\tcaller'
command -v jq >/dev/null 2>&1 || exit 0
INPUT=$(cat 2>/dev/null) || exit 0
[ "$(printf '%s' "$INPUT" | jq -r '.tool_name // ""' 2>/dev/null)" = "Skill" ] || exit 0
clean() { tr -cd 'A-Za-z0-9_.:-' | cut -c1-"$1"; }
SKILL=$(printf '%s' "$INPUT" | jq -r '(.tool_input.skill | select(type == "string" and test("\\A[A-Za-z0-9_.:-]+\\z"))) // ""' 2>/dev/null | clean 80)
[ -n "$SKILL" ] || exit 0
SID=$(printf '%s' "$INPUT" | jq -r '.session_id // ""' 2>/dev/null | clean 8)
CALLER=$(printf '%s' "$INPUT" | jq -r '.agent_type // ""' 2>/dev/null | clean 40)
: "${SID:=-}" "${CALLER:=main}"
DIR="$HOME/.claude/_usage"
LOG="$DIR/skill-usage.tsv"
[ -L "$DIR" ] && exit 0
umask 077
mkdir -p "$DIR" 2>/dev/null
[ -d "$DIR" ] && [ ! -L "$DIR" ] || exit 0
[ -L "$LOG" ] || [ -L "$LOG.lock" ] && exit 0
{
    command -v flock >/dev/null 2>&1 && { exec 9>>"$LOG.lock" && flock -w 3 9 || exit 0; }
    [ -L "$LOG" ] && exit 0
    if [ ! -e "$LOG" ]; then
        printf '%s\n' "$HEADER" >> "$LOG"
    elif [ -f "$LOG" ] && [ "$(stat -c %s "$LOG")" -gt "$MAX" ]; then
        TMP=$(mktemp "$DIR/.skill-usage.XXXXXX") || exit 0
        { printf '%s\n' "$HEADER"; tail -c "$((MAX / 2))" "$LOG" | tail -n +2; } > "$TMP"
        # NEVER: 머리줄만 든 임시 파일(읽기 오류 등)로 원본을 덮지 않는다. 그 회차는 덧붙이기만 한다.
        if [ "$(stat -c %s "$TMP")" -gt "$((${#HEADER} + 1))" ]; then mv -f "$TMP" "$LOG"; else rm -f "$TMP"; fi
    fi
    [ -f "$LOG" ] || exit 0
    printf '%s\t%s\t%s\t%s\n' "$(date -Is)" "$SID" "$SKILL" "$CALLER" >> "$LOG"
    chmod 600 "$LOG"
} 2>/dev/null
exit 0
