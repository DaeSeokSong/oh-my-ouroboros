#!/usr/bin/env bash
# PostToolUse(Write|Edit) hook — Graphify 자동 재인덱싱 (증분, 백그라운드)
#
# 목적: Graphify가 설정된 프로젝트에서 코드 파일이 Write/Edit로 변경될 때마다
#       graphify-out/graph.json을 백그라운드에서 자동 재인덱싱한다 (stale drift 방지).
#       사용자 편집 흐름은 절대 차단하지 않는다 — 모든 경로에서 exit 0. stdout 은 직전 재인덱싱의 완료·실패
#       보고 JSON(additionalContext)이 있을 때만 낸다.
# 등록: settings.json → hooks.PostToolUse (matcher: "Write|Edit")
#
# 가드 (모두 즉시 exit 0):
#   1. jq 미설치 또는 file_path 비어있음
#   2. graphify-out 보유 프로젝트 루트 미발견 (최대 15단계 walk-up, / 또는 $HOME 도달 시 중단)
#   3. 발견된 루트가 $HOME/.claude (하네스 격리)
#   4. 변경 파일 경로가 graphify-out/ 내부 (재귀 방지)
#   5. graphify 미설치 (command -v 실패)
#   6. debounce 120초 이내 재실행
#   7. lock 존재 + 10분 이내 (동시 실행 방지, 10분 초과 stale lock은 제거 후 진행)
# REF: knowledge/harness/code-history/scripts__graphify-autoindex.sh.md
set -uo pipefail

DEBOUNCE_SEC=120
LOCK_STALE_SEC=600
MAX_WALKUP=15
HOME_DIR="${HOME:-}"

INPUT=$(cat 2>/dev/null) || exit 0
command -v jq >/dev/null 2>&1 || exit 0

FILE_PATH=$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // empty' 2>/dev/null)
[ -z "${FILE_PATH:-}" ] && exit 0

case "$FILE_PATH" in
    /*) : ;;
    *) exit 0 ;;
esac

START_DIR=$(dirname -- "$FILE_PATH" 2>/dev/null) || exit 0
[ -z "${START_DIR:-}" ] && exit 0

ROOT=""
CUR="$START_DIR"
LEVELS=0
while :; do
    if [ -d "$CUR/graphify-out" ]; then
        ROOT="$CUR"
        break
    fi
    if [ "$CUR" = "/" ] || { [ -n "$HOME_DIR" ] && [ "$CUR" = "$HOME_DIR" ]; }; then
        break
    fi
    LEVELS=$((LEVELS + 1))
    [ "$LEVELS" -gt "$MAX_WALKUP" ] && break
    CUR=$(dirname -- "$CUR" 2>/dev/null) || break
done

[ -z "${ROOT:-}" ] && exit 0

# WHY: 상대 ROOT 면 백그라운드 `cd "$ROOT"` 뒤 마커가 엉뚱한 위치에 쓰여 실패가 침묵했다(2026-07-18 Codex).
# NEVER: pwd -P 를 빼지 않는다. 심링크 경로 편집에서 하네스 격리 비교가 어긋나 AST 빌드가 하네스 그래프를 오염시켰다(2026-07-31 실증, 1480→3134노드).
ROOT=$(cd "$ROOT" 2>/dev/null && pwd -P) || exit 0
[ -z "$ROOT" ] && exit 0

# WHY: $HOME/.claude 자체가 심링크인 서버에서는 물리화된 ROOT 와 일치하지 않아 가드가 무력화됐다(2026-08-07). $HOME/.claude 도 물리화해 비교한다.
if [ -n "$HOME_DIR" ]; then
    HARNESS_DIR=$(cd "$HOME_DIR/.claude" 2>/dev/null && pwd -P)
    [ -n "$HARNESS_DIR" ] && [ "$ROOT" = "$HARNESS_DIR" ] && exit 0
fi

case "$FILE_PATH" in
    "$ROOT"/graphify-out/*) exit 0 ;;
esac

GRAPH_DIR="$ROOT/graphify-out"

# WHY: 재인덱싱은 비동기라 완료 순간엔 보고 채널이 없어 다음 Write/Edit 훅 호출이 전달한다(2026-07-10 사용자 요청).
# PostToolUse 의 exit 0 평문 stdout 은 모델에 전달되지 않고(공식 문서, 2026-10-01 감사) 한 호출에 JSON 은 하나여야 해 CTX 에 모아 한 번만 낸다.
CTX=""
if [ -f "$GRAPH_DIR/.autoindex-updated" ]; then
    CTX="[graphify] $(cat "$GRAPH_DIR/.autoindex-updated" 2>/dev/null) — 코드 그래프 자동 갱신 완료"
    rm -f "$GRAPH_DIR/.autoindex-updated" 2>/dev/null
fi
# WHY: 종전엔 .autoindex-failed 를 쓰기만 하고 보고 안 해 graphify 실패가 침묵했다(2026-07-18 Codex).
if [ -f "$GRAPH_DIR/.autoindex-failed" ]; then
    CTX="${CTX:+$CTX
}[graphify] ⚠️ $(cat "$GRAPH_DIR/.autoindex-failed" 2>/dev/null) — 코드 그래프 자동 갱신 실패 (수동 graphify update . 확인)"
    rm -f "$GRAPH_DIR/.autoindex-failed" 2>/dev/null
fi
[ -n "$CTX" ] && jq -nc --arg m "$CTX" '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: $m}}'

command -v graphify >/dev/null 2>&1 || exit 0

MARKER="$GRAPH_DIR/.autoindex-last"
LOCK="$GRAPH_DIR/.autoindex-lock"
NOW=$(date +%s 2>/dev/null) || exit 0

# WHY: debounce 는 의도적으로 leading-edge 다. 120초 창 안의 후속 edit 은 창 밖 다음 edit 이 자가 치유하고,
# 하네스 그래프는 나이틀리 타이머가 빌드해 순간 stale 은 correctness 와 무관하다(2026-07-18 Codex).
if [ -f "$MARKER" ]; then
    LAST=$(stat -c %Y "$MARKER" 2>/dev/null || stat -f %m "$MARKER" 2>/dev/null)
    if [ -n "${LAST:-}" ]; then
        AGE=$((NOW - LAST))
        [ "$AGE" -lt "$DEBOUNCE_SEC" ] && exit 0
    fi
fi
touch "$MARKER" 2>/dev/null || exit 0

# WHY: mkdir 원자적 획득으로 check-then-touch 경합을 없앤다(2026-07-06 Codex F12).
if [ -d "$LOCK" ]; then
    LOCK_TS=$(stat -c %Y "$LOCK" 2>/dev/null || stat -f %m "$LOCK" 2>/dev/null)
    if [ -n "${LOCK_TS:-}" ]; then
        LOCK_AGE=$((NOW - LOCK_TS))
        if [ "$LOCK_AGE" -lt "$LOCK_STALE_SEC" ]; then
            exit 0
        fi
        # NEVER: owner PID 가 살아 있는 stale 후보(>10min) lock 을 지우지 않는다. 느린 실행이라 동시 실행+손상이 된다(2026-07-18 Codex).
        OWNER_PID=$(cut -d- -f1 "$LOCK/owner" 2>/dev/null)
        [ -n "${OWNER_PID:-}" ] && kill -0 "$OWNER_PID" 2>/dev/null && exit 0
    fi
    rm -rf "$LOCK" 2>/dev/null || exit 0
fi
mkdir "$LOCK" 2>/dev/null || exit 0

# WHY: owner 토큰은 워커 서브셸의 $BASHPID 다. 부모 훅 $$ 는 즉시 종료돼 liveness 체크가 무의미했다(2026-07-18 Codex 재지적).
# 락 해제는 내 토큰일 때만 한다. 타 프로세스가 내 stale lock 제거 후 재획득했으면 건드리지 않는다.
( MYTOKEN="$BASHPID-$(date +%s 2>/dev/null || echo 0)"
  echo "$MYTOKEN" > "$LOCK/owner" 2>/dev/null
  # NEVER: `graphify .` 로 바꾸지 않는다. pending 문서가 있으면 LLM API 키를 요구하며 exit 1 로 중단된다(2026-07-31 한 프로젝트의 8일 정체 실증).
  cd "$ROOT" 2>/dev/null && graphify update . >/dev/null 2>&1 \
    && printf '%s %s' "$(date '+%m-%d %H:%M')" "$(basename "$ROOT")" > "$GRAPH_DIR/.autoindex-updated" 2>/dev/null \
    || printf '%s %s FAIL' "$(date '+%m-%d %H:%M')" "$(basename "$ROOT")" > "$GRAPH_DIR/.autoindex-failed" 2>/dev/null
  [ "$(cat "$LOCK/owner" 2>/dev/null)" = "$MYTOKEN" ] && rm -rf "$LOCK" 2>/dev/null ) &

exit 0
