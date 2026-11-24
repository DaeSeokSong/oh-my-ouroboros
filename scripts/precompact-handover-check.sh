#!/usr/bin/env bash
# precompact-handover-check.sh — PreCompact 훅: handover.md 가 오래됐으면 한 줄 경고
#   세션 cwd 와 그 git 뿌리의 프로젝트 memory(`~/.claude/projects/<cwd 이름>/memory/short-term/handover.md`)에 그 파일이 있을 때만 본다. 없으면 침묵한다.
#   mtime 이 60분을 넘으면 경과 분을 붙여 systemMessage 한 줄로 낸다. 차단하지 않고 항상 exit 0 이다.
# REF: knowledge/harness/code-history/scripts__precompact-handover-check.sh.md
set -uo pipefail

INPUT=$(cat 2>/dev/null) || INPUT=""

# WHY: short-term 뿌리는 저장소가 아니라 `~/.claude/projects/<cwd 이름>/memory/` 다(rules-lazy/memory-write.md § 메모리 구조).
# 종전의 `<저장소>/short-term/handover.md` 는 존재하지 않는 폴더라 훅이 한 번도 경고하지 못했다(2026-10-01 감사).
CWD=$(printf '%s' "$INPUT" | jq -r '.cwd // empty' 2>/dev/null)
[ -n "$CWD" ] || CWD="$(pwd 2>/dev/null || echo .)"
FILE=""
for DIR in "$CWD" "$(git -C "$CWD" rev-parse --show-toplevel 2>/dev/null)"; do
    [ -n "$DIR" ] || continue
    CAND="$HOME/.claude/projects/$(printf '%s' "$DIR" | sed 's/[^A-Za-z0-9]/-/g')/memory/short-term/handover.md"
    [ -f "$CAND" ] && { FILE="$CAND"; break; }
done
[ -n "$FILE" ] || exit 0

NOW=$(date +%s 2>/dev/null || echo 0)
MTIME=$(stat -c %Y "$FILE" 2>/dev/null || echo "$NOW")
AGE=$(( (NOW - MTIME) / 60 ))

if [ "$AGE" -gt 60 ]; then
    # WHY: PreCompact 는 additionalContext 를 지원하지 않고 평문 stdout 도 모델에 안 닿는다(공식 문서, 2026-10-01 감사).
    # systemMessage 로 사용자에게 보인다.
    MSG=$(printf '⚠ HANDOVER_STALE: handover.md 가 %d분 전 — compact 전 갱신(context-management.md § compact 직전 절차)' "$AGE")
    jq -nc --arg m "$MSG" '{systemMessage: $m}'
fi
exit 0
