#!/usr/bin/env bash
# PostToolUse(Bash) hook — Graphify 커밋 트리거 재인덱싱 (증분, 백그라운드)
#
# 목적: Claude Code로 작업 중 `git commit`이 실행되면, 해당 graphify 프로젝트의
#       graph.json을 백그라운드 재인덱싱한다. autoindex(Write|Edit) 훅은 Claude의
#       파일 편집만 잡으므로, 외부 에디터/스크립트로 편집한 뒤 커밋한 변경분은
#       이 훅이 보완한다 (커밋 = "Claude가 그 변경을 처음 보는 시점").
# 등록: settings.json → hooks.PostToolUse (matcher: "Bash")
# 계약 · 한계:
#   - 외부 터미널 직접 커밋(Claude Code 밖)은 이 훅을 안 거치나, code-graph.md §2의
#     소비-직전 freshness 검사(main·scout·coder·qa)가 correctness 최후 보루.
#   - 하네스(~/.claude) 커밋은 제외 — 하네스 온톨로지는 마크다운 semantic 추출(LLM)이
#     필요해 AST-only `graphify .`로 갱신하면 안 됨(§7 나이틀리 타이머 경로만).
#   - 락·debounce 마커를 autoindex와 **공유**(.autoindex-lock/.autoindex-last) →
#     편집 직후(≤120s) 커밋은 debounce로 스킵(이미 편집 시 빌드됨), 이중 빌드 없음.
# 참고: 로직·가드는 graphify-autoindex.sh를 그대로 따름 (트리거·입력 파싱만 상이).
# REF: knowledge/harness/code-history/scripts__graphify-commit-refresh.sh.md
set -uo pipefail

DEBOUNCE_SEC=120
LOCK_STALE_SEC=600
MAX_WALKUP=15
HOME_DIR="${HOME:-}"

INPUT=$(cat 2>/dev/null) || exit 0
command -v jq >/dev/null 2>&1 || exit 0

CMD=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)
[ -z "${CMD:-}" ] && exit 0

printf '%s' "$CMD" | grep -qE '(^|[;&|[:space:]])git[[:space:]]+commit([[:space:]]|$)' || exit 0

# NEVER: eval 을 쓰지 않는다(주입). sed로 인용부호 안 경로만 추출.
CWD=$(printf '%s' "$INPUT" | jq -r '.cwd // empty' 2>/dev/null)
CDTARGET=$(printf '%s' "$CMD" | sed -nE 's/^[[:space:]]*cd[[:space:]]+"?([^"&;|]+)"?[[:space:]]*&&.*/\1/p' | head -1)
CDTARGET=$(printf '%s' "${CDTARGET:-}" | sed -e 's/[[:space:]]*$//')
# shellcheck disable=SC2088  # "~/" is a literal case pattern for a cd target typed with a tilde, not a path to expand
case "$CDTARGET" in
    "~") CDTARGET="$HOME_DIR" ;;
    "~/"*) CDTARGET="$HOME_DIR/${CDTARGET#\~/}" ;;
esac
case "$CDTARGET" in
    "") START_DIR="$CWD" ;;
    /*) START_DIR="$CDTARGET" ;;
    *) START_DIR="$CWD/$CDTARGET" ;;
esac
[ -z "${START_DIR:-}" ] && exit 0
[ -d "$START_DIR" ] || START_DIR="$CWD"
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

# WHY: 마커 write/read 경로를 autoindex와 맞춘다. pwd -P(물리 경로) 필수 (2026-07-31): 심링크 경로(~/workspace/.claude) 유입 시 논리 pwd로는
# 하네스 격리 비교가 불일치해 우회됨 — autoindex와 동일 교정.
ROOT=$(cd "$ROOT" 2>/dev/null && pwd -P) || exit 0
[ -z "$ROOT" ] && exit 0

# NEVER: ~/.claude 에 AST-only update 를 돌리지 않는다. 하네스 온톨로지는 §7 나이틀리 타이머만.
# WHY: $HOME/.claude가 심링크인 서버에서 물리화된 ROOT와 심링크 문자열이 불일치해 가드가 무력화됐다(2026-08-07).
# $HOME/.claude도 물리화 후 비교한다 — autoindex와 동일.
if [ -n "$HOME_DIR" ]; then
    HARNESS_DIR=$(cd "$HOME_DIR/.claude" 2>/dev/null && pwd -P)
    [ -n "$HARNESS_DIR" ] && [ "$ROOT" = "$HARNESS_DIR" ] && exit 0
fi

GRAPH_DIR="$ROOT/graphify-out"

if [ -f "$GRAPH_DIR/.autoindex-updated" ]; then
    echo "[graphify] $(cat "$GRAPH_DIR/.autoindex-updated" 2>/dev/null) — 코드 그래프 자동 갱신 완료"
    rm -f "$GRAPH_DIR/.autoindex-updated" 2>/dev/null
fi
if [ -f "$GRAPH_DIR/.autoindex-failed" ]; then
    echo "[graphify] ⚠️ $(cat "$GRAPH_DIR/.autoindex-failed" 2>/dev/null) — 코드 그래프 자동 갱신 실패 (수동 graphify update . 확인)"
    rm -f "$GRAPH_DIR/.autoindex-failed" 2>/dev/null
fi

command -v graphify >/dev/null 2>&1 || exit 0

MARKER="$GRAPH_DIR/.autoindex-last"
LOCK="$GRAPH_DIR/.autoindex-lock"
NOW=$(date +%s 2>/dev/null) || exit 0

if [ -f "$MARKER" ]; then
    LAST=$(stat -c %Y "$MARKER" 2>/dev/null || stat -f %m "$MARKER" 2>/dev/null)
    if [ -n "${LAST:-}" ]; then
        AGE=$((NOW - LAST))
        [ "$AGE" -lt "$DEBOUNCE_SEC" ] && exit 0
    fi
fi
touch "$MARKER" 2>/dev/null || exit 0

if [ -d "$LOCK" ]; then
    LOCK_TS=$(stat -c %Y "$LOCK" 2>/dev/null || stat -f %m "$LOCK" 2>/dev/null)
    if [ -n "${LOCK_TS:-}" ]; then
        LOCK_AGE=$((NOW - LOCK_TS))
        if [ "$LOCK_AGE" -lt "$LOCK_STALE_SEC" ]; then
            exit 0
        fi
        OWNER_PID=$(cut -d- -f1 "$LOCK/owner" 2>/dev/null)
        [ -n "${OWNER_PID:-}" ] && kill -0 "$OWNER_PID" 2>/dev/null && exit 0
    fi
    rm -rf "$LOCK" 2>/dev/null || exit 0
fi
mkdir "$LOCK" 2>/dev/null || exit 0

( MYTOKEN="$BASHPID-$(date +%s 2>/dev/null || echo 0)"
  echo "$MYTOKEN" > "$LOCK/owner" 2>/dev/null
  # WHY: `graphify .`가 아닌 `graphify update .`(코드 전용) — pending 문서가 1건이라도 있으면
  # `graphify .`는 LLM API 키를 요구하며 exit 1 전체 중단 (2026-07-31 한 프로젝트의 8일 정체 실증:
  # 문서 107건 pending → headless 훅 무키 환경에서 코드 291건 갱신까지 통째 실패)
  cd "$ROOT" 2>/dev/null && graphify update . >/dev/null 2>&1 \
    && printf '%s %s' "$(date '+%m-%d %H:%M')" "$(basename "$ROOT")" > "$GRAPH_DIR/.autoindex-updated" 2>/dev/null \
    || printf '%s %s FAIL' "$(date '+%m-%d %H:%M')" "$(basename "$ROOT")" > "$GRAPH_DIR/.autoindex-failed" 2>/dev/null
  [ "$(cat "$LOCK/owner" 2>/dev/null)" = "$MYTOKEN" ] && rm -rf "$LOCK" 2>/dev/null ) &

exit 0
