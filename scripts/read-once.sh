#!/usr/bin/env bash
# read-once: Read 중복 읽기 차단 훅 (3모드)
#   기본 모드      = PreToolUse(Read):  캐시 검사만 — 차단/통과 판단, 기록 없음
#   --record 모드  = PostToolUse(Read): Read가 실제로 성공한 뒤에만 캐시 기록
#   --clear 모드   = PreCompact:        캐시 전체 비우기
# 동일 파일 + 동일 mtime 재읽기 차단. TTL 1200초(20분). 부분 읽기(offset · limit · pages)는 캐시를 쓰지 않는다.
# 캐시 키는 sha256(session_id:agent_id:path) 라 세션·에이전트 격리다. --clear 는 CACHE_DIR 의 *.cache 전부를 지운다.
# REF: knowledge/harness/code-history/scripts__read-once.sh.md

set -uo pipefail

MODE="check"
[ "${1:-}" = "--record" ] && MODE="record"
[ "${1:-}" = "--clear" ] && MODE="clear"

CACHE_DIR="$HOME/.claude/_cache/read-once"
TTL="${READ_ONCE_TTL:-1200}"
mkdir -p "$CACHE_DIR"

if [ "$MODE" = "clear" ]; then
    # WHY: compact 뒤에는 읽은 파일 내용이 컨텍스트에서 사라지므로 재읽기가 정상 동작이다(2026-09-08 사용자 결정).
    # 캐시 파일 이름(해시)으로는 세션을 되짚을 수 없어 전부 지운다. 지워서 생기는 최악은 다른 세션의 재읽기 1회다.
    rm -f "$CACHE_DIR"/*.cache 2>/dev/null
    exit 0
fi

INPUT=$(cat)
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)
[ "$TOOL" != "Read" ] && exit 0

FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
OFFSET=$(echo "$INPUT" | jq -r '.tool_input.offset // empty' 2>/dev/null)
LIMIT=$(echo "$INPUT" | jq -r '.tool_input.limit // empty' 2>/dev/null)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // "global"' 2>/dev/null)
# WHY: session_id 는 부모와 서브에이전트가 같다(구분은 agent_id, 2026-10-01 감사). 키에 agent_id 가 없으면
# 서브에이전트가 읽은 파일을 부모가 «이미 읽음» 으로 오차단하거나 그 반대가 된다.
AGENT_ID=$(echo "$INPUT" | jq -r '.agent_id // empty' 2>/dev/null)
PAGES=$(echo "$INPUT" | jq -r '.tool_input.pages // empty' 2>/dev/null)

# WHY: pages(PDF 쪽 범위)도 부분 읽기다. 빠뜨리면 다음 쪽 범위가 차단됐다(2026-10-01 감사).
[ -n "$OFFSET" ] && exit 0
[ -n "$LIMIT" ] && exit 0
[ -n "$PAGES" ] && exit 0
[ -z "$FILE_PATH" ] && exit 0
[ ! -f "$FILE_PATH" ] && exit 0

PATH_HASH=$(echo -n "${SESSION_ID}:${AGENT_ID}:${FILE_PATH}" | sha256sum | cut -c1-16)
# WHY: 초 단위 mtime 만으로는 같은 초의 수정을 못 잡아 오차단한다(2026-07-18 Codex). 동일 크기·동일 초 편집은 잔여 한계다.
MTIME=$(stat -c %Y "$FILE_PATH" 2>/dev/null || stat -f %m "$FILE_PATH" 2>/dev/null)
FSIZE=$(stat -c %s "$FILE_PATH" 2>/dev/null || stat -f %z "$FILE_PATH" 2>/dev/null || echo 0)
SIG="${MTIME}:${FSIZE}"
CACHE_FILE="$CACHE_DIR/${PATH_HASH}.cache"
NOW=$(date +%s)

if [ "$MODE" = "record" ]; then
    ERR=$(echo "$INPUT" | jq -r '.tool_response.error // empty' 2>/dev/null)
    [ -n "$ERR" ] && exit 0
    echo "$SIG $NOW" > "$CACHE_FILE"
    exit 0
fi

# NEVER: check 모드에서 기록하지 않는다. 실패한 Read 까지 기록하면 TTL 동안 재읽기가 차단된다(2026-07-15 GPT 교차감사 FINDING 4.4).
if [ -f "$CACHE_FILE" ]; then
    CACHED=$(cat "$CACHE_FILE")
    CACHED_SIG=$(echo "$CACHED" | cut -d' ' -f1)
    CACHED_TS=$(echo "$CACHED" | cut -d' ' -f2)
    AGE=$((NOW - CACHED_TS))
    if [ "$CACHED_SIG" = "$SIG" ] && [ "$AGE" -lt "$TTL" ]; then
        # WHY: 문자열 보간은 파일명의 따옴표·백슬래시·개행에 JSON 이 깨져 fail-open(차단 무효)됐다(2026-07-18 Codex).
        if command -v jq >/dev/null 2>&1; then
            jq -cn --arg f "$FILE_PATH" '{decision:"block", reason:("이미 읽은 파일(" + $f + ") — 변경 없음. 메모리에서 참조하세요. TTL 후 재읽기 가능.")}'
        else
            echo "{\"decision\":\"block\",\"reason\":\"이미 읽은 파일 — 변경 없음. 메모리에서 참조하세요. TTL 후 재읽기 가능.\"}"
        fi
        exit 0
    fi
fi
exit 0
