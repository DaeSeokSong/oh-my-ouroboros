#!/usr/bin/env bash
# scope-gate.sh — PreToolUse hook for Write/Edit
# Checks if target file path is in the registered scope; otherwise block.
set -u

INPUT="$(cat)"
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // empty' 2>/dev/null)
SESSION=$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)

# Empty file path → allow (other hooks handle it)
[ -z "$FILE" ] && exit 0

# 경로 정규화 (2026-07-18 Codex): `~/.claude/../outside`·심볼릭이 비정규 접두 매칭으로 scope를
# 우회하는 것 방지 — case 매칭 전에 `..`·심볼릭을 해소한 절대경로로 치환 (-m: 미존재 경로도 처리).
CANON=$(realpath -m "$FILE" 2>/dev/null) && [ -n "$CANON" ] && FILE="$CANON"

# ~/.claude 메타 작업은 예외 (런타임 디렉토리 제외)
case "$FILE" in
  "${HOME}/.claude/projects/"*|"${HOME}/.claude/jobs/"*|"${HOME}/.claude/teams/"*|"${HOME}/.claude/daemon"*)
    ;; # fall through to scope check
  "${HOME}/.claude/"*)
    exit 0 ;; # meta work, allow
esac

# 세션별 scope 파일 우선 (rules-lazy/scope-gate.md: ~/.claude/scope/{session_id}.json)
# 과거: 전역 최신 파일 사용 → 병렬 세션 간 교차 오작동 (2026-07-06 Codex 교차검증 F11 수정)
SCOPE_DIR="$HOME/.claude/scope"
[ ! -d "$SCOPE_DIR" ] && exit 0  # no scope registered → allow (legacy behavior)

if [ -n "$SESSION" ]; then
  LATEST="$SCOPE_DIR/$SESSION.json"
  [ ! -f "$LATEST" ] && exit 0  # 이 세션에 등록된 scope 없음 → 게이트 비활성 (allow)
else
  # session_id 미제공(구버전 호환) → 최신 파일 fallback
  LATEST=$(ls -1t "$SCOPE_DIR"/*.json 2>/dev/null | head -1)
  [ -z "$LATEST" ] && exit 0  # no scope file → allow
fi

# Check if file is in scope
IN_SCOPE=$(jq -r --arg f "$FILE" '.scope[] | select(.path == $f) | .path' "$LATEST" 2>/dev/null)
if [ -z "$IN_SCOPE" ]; then
  REASON="scope-gate: $FILE is not in the registered scope ($LATEST). 사전 합의된 범위 외 파일 수정·삭제는 사용자 승인이 필요합니다."
  printf '{"decision": "block", "reason": %s}\n' "$(printf '%s' "$REASON" | jq -R -s .)"
fi

exit 0
