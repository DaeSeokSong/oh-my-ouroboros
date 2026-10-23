#!/usr/bin/env bash
# read-once: Read 중복 읽기 차단 훅 (3모드)
#   기본 모드      = PreToolUse(Read):  캐시 검사만 — 차단/통과 판단, 기록 없음
#   --record 모드  = PostToolUse(Read): Read가 실제로 성공한 뒤에만 캐시 기록
#   --clear 모드   = PreCompact:        캐시 전체 비우기 (아래 근거)
# 동일 파일 + 동일 mtime 재읽기 차단. TTL 1200초(20분).
#
# 기록 시점 분리 근거 (2026-07-15 — GPT 교차감사 FINDING 4.4): 종전에는 PreToolUse에서
# 성공 여부와 무관하게 기록해, Read가 실패(대용량 등)해도 TTL 동안 재읽기가 차단됐다.
# 성공한 읽기만 기록해야 "메모리에서 참조하세요" 안내가 참이 된다.
#
# --clear 근거 (2026-09-08 사용자 결정): compact 뒤에는 읽은 파일 내용이 컨텍스트에서 사라지므로
# 재읽기가 정상 동작이다. 그런데 캐시는 TTL 20분을 그대로 세므로 "메모리에서 참조하세요" 안내가
# 거짓이 된다. PreCompact 에서 캐시를 비워 compact 직후 재읽기를 열어 준다.
# 캐시 키는 sha256(session_id:agent_id:path) 라 세션·에이전트 격리이지만 **파일 이름만으로는 세션을 되짚을 수 없다**
# (해시 안에 들어 있어 역산 불가). 그래서 --clear 는 CACHE_DIR 의 *.cache 전부를 지운다 —
# 지워서 생기는 최악은 다른 세션의 재읽기 1회이므로 안전한 쪽으로 넓게 지운다.

set -uo pipefail

MODE="check"
[ "${1:-}" = "--record" ] && MODE="record"
[ "${1:-}" = "--clear" ] && MODE="clear"

CACHE_DIR="$HOME/.claude/_cache/read-once"
TTL="${READ_ONCE_TTL:-1200}"
mkdir -p "$CACHE_DIR"

if [ "$MODE" = "clear" ]; then
    # stdin 을 읽지 않는다 — PreCompact 훅 입력 JSON 은 이 모드에서 쓸 데가 없다.
    rm -f "$CACHE_DIR"/*.cache 2>/dev/null
    exit 0
fi

INPUT=$(cat)
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)
[ "$TOOL" != "Read" ] && exit 0

FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
OFFSET=$(echo "$INPUT" | jq -r '.tool_input.offset // empty' 2>/dev/null)
LIMIT=$(echo "$INPUT" | jq -r '.tool_input.limit // empty' 2>/dev/null)
# 세션 격리 — 캐시 키에 session_id 포함. 미포함 시 다른 세션/subagent가 읽은 파일이
# 이 세션에서 오차단됨("메모리에서 참조" 안내가 거짓이 되는 케이스). scope-gate와 동일 패턴.
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // "global"' 2>/dev/null)
# 2026-10-01 감사: session_id 는 부모와 서브에이전트가 같다(구분은 agent_id). 키에 agent_id 를 넣어야 위 «격리» 가 성립한다 —
# 아니면 서브에이전트가 읽은 파일을 부모가 «이미 읽음» 으로 오차단(부모 컨텍스트엔 내용이 없다)하거나 그 반대가 된다.
AGENT_ID=$(echo "$INPUT" | jq -r '.agent_id // empty' 2>/dev/null)
PAGES=$(echo "$INPUT" | jq -r '.tool_input.pages // empty' 2>/dev/null)

# 부분 읽기는 캐시 미적용 — 통과 (pages: PDF 쪽 범위도 부분 읽기. 2026-10-01 감사: 다음 쪽 범위가 차단되던 것)
[ -n "$OFFSET" ] && exit 0
[ -n "$LIMIT" ] && exit 0
[ -n "$PAGES" ] && exit 0
[ -z "$FILE_PATH" ] && exit 0
[ ! -f "$FILE_PATH" ] && exit 0

PATH_HASH=$(echo -n "${SESSION_ID}:${AGENT_ID}:${FILE_PATH}" | sha256sum | cut -c1-16)
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
