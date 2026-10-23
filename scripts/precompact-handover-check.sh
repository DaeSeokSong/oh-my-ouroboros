#!/usr/bin/env bash
# precompact-handover-check.sh — PreCompact 훅: handover.md 가 오래됐으면 한 줄 경고 (2026-09-14)
#
# ■ 왜 훅인가 (판단 근거 이식)
#   «자동 compact 75% 도달 시 Mem0 백업(T02) → handover.md → compact 순서 강제»(CLAUDE.md § 컨텍스트 관리)는
#   정본이 모델 의무뿐이라, 자동 compact 가 발동하면 그 순서를 수행할 턴 자체가 없다. 2026-09-14 감사가
#   «PreCompact 에 T02·handover 수행 턴도 훅도 없다»로 지목한 구멍이다(_audit/loop-audit-20260914.md §3).
#   훅은 compact 직전에 반드시 실행되므로, 최소한 «지금 handover 가 낡았다»는 사실은 결정적으로 알릴 수 있다.
#
# ■ 왜 경고만인가
#   compact 는 컨텍스트가 한계에 닿아 발동한다. 여기서 차단하면 세션이 진행 불능이 된다.
#   그래서 판단 재료만 주고 항상 exit 0 이다(train-launch-warn.sh 와 같은 «경고만» 방침).
#
# ■ 판정
#   세션 cwd 의 프로젝트 memory(`~/.claude/projects/<cwd 이름>/memory/short-term/handover.md`)에 그 파일이 **있을 때만** 본다. 없으면 침묵한다 —
#   handover 를 쓰지 않는 저장소(문서·도구 저장소)에까지 경보를 내면 경고가 배경 소음이 된다.
#   mtime 이 60분을 넘으면 경과 분을 붙여 한 줄 출력한다.
set -uo pipefail

INPUT=$(cat 2>/dev/null) || INPUT=""   # 훅 payload(JSON) 소비 — 읽지 않으면 호출부가 SIGPIPE 를 볼 수 있다. cwd 를 쓰므로 변수로 받는다

# handover 의 실제 위치 (2026-10-01 감사): 규칙(memory-write.md § 메모리 구조)의 short-term 뿌리는 저장소가 아니라
# `~/.claude/projects/<cwd 를 영숫자 외 문자 → '-' 로 바꾼 이름>/memory/` 다. 종전의 `<저장소>/short-term/handover.md` 는
# 존재하지 않는 폴더라 훅이 한 번도 경고하지 못했다. 세션 cwd(payload.cwd)와 그 git 뿌리를 차례로 본다.
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
    # PreCompact 는 additionalContext 를 지원하지 않는다(공식 문서) — 평문 stdout 도 모델에 안 닿으므로 systemMessage 로
    # 사용자에게 보인다(2026-10-01 감사). 차단은 아니다.
    MSG=$(printf '⚠ HANDOVER_STALE: handover.md 가 %d분 전 — compact 전 갱신(context-management.md § compact 직전 절차)' "$AGE")
    jq -nc --arg m "$MSG" '{systemMessage: $m}'
fi
exit 0
