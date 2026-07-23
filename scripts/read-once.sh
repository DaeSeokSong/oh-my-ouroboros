#!/usr/bin/env bash
# read-once: Read 중복 읽기 차단 훅 (2모드)
#   기본 모드      = PreToolUse(Read):  캐시 검사만 — 차단/통과 판단, 기록 없음
#   --record 모드  = PostToolUse(Read): Read가 실제로 성공한 뒤에만 캐시 기록
# 동일 파일 + 동일 mtime 재읽기 차단. TTL 1200초(20분).
#
# 기록 시점 분리 근거 (2026-07-15 — GPT 교차감사 FINDING 4.4): 종전에는 PreToolUse에서
# 성공 여부와 무관하게 기록해, Read가 실패(대용량 등)해도 TTL 동안 재읽기가 차단됐다.
# 성공한 읽기만 기록해야 "메모리에서 참조하세요" 안내가 참이 된다.

set -uo pipefail

MODE="check"
[ "${1:-}" = "--record" ] && MODE="record"

CACHE_DIR="$HOME/.claude/_cache/read-once"
TTL="${READ_ONCE_TTL:-1200}"
mkdir -p "$CACHE_DIR"

INPUT=$(cat)
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)
[ "$TOOL" != "Read" ] && exit 0

FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
OFFSET=$(echo "$INPUT" | jq -r '.tool_input.offset // empty' 2>/dev/null)
LIMIT=$(echo "$INPUT" | jq -r '.tool_input.limit // empty' 2>/dev/null)
# 세션 격리 — 캐시 키에 session_id 포함. 미포함 시 다른 세션/subagent가 읽은 파일이
# 이 세션에서 오차단됨("메모리에서 참조" 안내가 거짓이 되는 케이스). scope-gate와 동일 패턴.
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // "global"' 2>/dev/null)

# 부분 읽기는 캐시 미적용 — 통과
[ -n "$OFFSET" ] && exit 0
[ -n "$LIMIT" ] && exit 0
[ -z "$FILE_PATH" ] && exit 0
[ ! -f "$FILE_PATH" ] && exit 0

PATH_HASH=$(echo -n "${SESSION_ID}:${FILE_PATH}" | sha256sum | cut -c1-16)
# mtime + size 조합 (2026-07-18 Codex): 초 단위 mtime만으로는 같은 초의 수정을 못 잡아 오차단 →
# 크기 변화를 함께 봐 대부분의 동일-초 편집을 감지 (동일 크기·동일 초 편집은 잔여 한계).
MTIME=$(stat -c %Y "$FILE_PATH" 2>/dev/null || stat -f %m "$FILE_PATH" 2>/dev/null)
FSIZE=$(stat -c %s "$FILE_PATH" 2>/dev/null || stat -f %z "$FILE_PATH" 2>/dev/null || echo 0)
SIG="${MTIME}:${FSIZE}"
CACHE_FILE="$CACHE_DIR/${PATH_HASH}.cache"
NOW=$(date +%s)

if [ "$MODE" = "record" ]; then
    # PostToolUse: Read 성공 후에만 도달. 방어적으로 tool_response에 error가 있으면 기록 스킵
    ERR=$(echo "$INPUT" | jq -r '.tool_response.error // empty' 2>/dev/null)
    [ -n "$ERR" ] && exit 0
    echo "$SIG $NOW" > "$CACHE_FILE"
    exit 0
fi

# check 모드 (PreToolUse): 검사만 — 여기서 기록하지 않는다 (실패한 Read가 캐시를 오염시키지 않도록)
if [ -f "$CACHE_FILE" ]; then
    CACHED=$(cat "$CACHE_FILE")
    CACHED_SIG=$(echo "$CACHED" | cut -d' ' -f1)
    CACHED_TS=$(echo "$CACHED" | cut -d' ' -f2)
    AGE=$((NOW - CACHED_TS))
    if [ "$CACHED_SIG" = "$SIG" ] && [ "$AGE" -lt "$TTL" ]; then
        # jq로 JSON 안전 생성 (2026-07-18 Codex): 파일명의 따옴표·백슬래시·개행이 문자열 보간
        # JSON을 깨뜨려 fail-open(차단 무효)되던 것 방지. jq 부재 시에만 문자열 폴백.
        if command -v jq >/dev/null 2>&1; then
            jq -cn --arg f "$FILE_PATH" '{decision:"block", reason:("이미 읽은 파일(" + $f + ") — 변경 없음. 메모리에서 참조하세요. TTL 후 재읽기 가능.")}'
        else
            echo "{\"decision\":\"block\",\"reason\":\"이미 읽은 파일 — 변경 없음. 메모리에서 참조하세요. TTL 후 재읽기 가능.\"}"
        fi
        exit 0
    fi
fi
exit 0
