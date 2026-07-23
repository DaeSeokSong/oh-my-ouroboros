#!/usr/bin/env bash
# CI Gate: PostToolUse 후속 자동 리뷰
# Edit/Write 도구 사용 후 수정된 파일 lint 검사 + 결과 출력 (non-blocking)
# 입력: stdin JSON (tool_name + tool_input.file_path)
# 출력: stderr (Claude Code가 사용자에게 표시)
# 종료: 항상 0 (비차단)

set -uo pipefail

INPUT=$(cat)
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)

# 입력 검증
[ -z "$FILE_PATH" ] && exit 0
[ ! -f "$FILE_PATH" ] && exit 0

# 확장자 분기
EXT="${FILE_PATH##*.}"
RESULT=""

case "$EXT" in
    py)
        if command -v ruff &>/dev/null; then
            RESULT=$(ruff check "$FILE_PATH" 2>&1 | head -20)
        fi
        ;;
    ts|tsx|js|jsx)
        if command -v eslint &>/dev/null; then
            RESULT=$(eslint "$FILE_PATH" 2>&1 | head -20)
        fi
        ;;
    go)
        if command -v gofmt &>/dev/null; then
            RESULT=$(gofmt -l "$FILE_PATH" 2>&1 | head -10)
        fi
        ;;
    rs)
        if command -v cargo &>/dev/null; then
            # rust는 프로젝트 단위 검증이 일반적이므로 syntax check만
            RESULT=$(rustc --edition=2021 --crate-type=lib --emit=metadata -o /dev/null "$FILE_PATH" 2>&1 | head -10)
        fi
        ;;
    java)
        # .class 산출물을 공유 /tmp에 직접 쓰면 누적·병렬 훅 간 충돌 — 격리 임시 디렉토리에 생성 후 즉시 삭제
        if command -v javac &>/dev/null && JAVAC_OUT=$(mktemp -d "${TMPDIR:-/tmp}/ci-gate-javac.XXXXXX" 2>/dev/null); then
            RESULT=$(javac -Xlint -d "$JAVAC_OUT" "$FILE_PATH" 2>&1 | head -10)
            rm -rf "$JAVAC_OUT"
        fi
        ;;
    cpp|cc|cxx|c|h|hpp)
        if command -v g++ &>/dev/null; then
            RESULT=$(g++ -Wall -fsyntax-only "$FILE_PATH" 2>&1 | head -10)
        fi
        ;;
    sh|bash)
        if command -v shellcheck &>/dev/null; then
            RESULT=$(shellcheck "$FILE_PATH" 2>&1 | head -20)
        fi
        ;;
    md|markdown)
        if command -v markdownlint &>/dev/null; then
            RESULT=$(markdownlint "$FILE_PATH" 2>&1 | head -20)
        else
            # markdownlint 없으면 단순 검사: 빈 링크, 미닫힘 코드 펜스
            # grep -c는 무매치에도 "0"을 출력하고 exit 1 → $()안 `|| echo 0`은 "0\n0"을 만들어
            # 산술 abort(hook 실패). `||`를 밖으로 빼서 단일 숫자 보장 (2026-07-18 Codex).
            FENCE_COUNT=$(grep -c '^```' "$FILE_PATH" 2>/dev/null); FENCE_COUNT=${FENCE_COUNT:-0}
            if [ $((FENCE_COUNT % 2)) -ne 0 ]; then
                RESULT="⚠️ Code fence imbalance detected (count: $FENCE_COUNT)"
            fi
        fi
        ;;
    *)
        exit 0
        ;;
esac

# 결과 출력
if [ -n "$RESULT" ] && [ "$RESULT" != "All checks passed!" ]; then
    echo "" >&2
    echo "🔍 [ci-gate] $FILE_PATH:" >&2
    echo "$RESULT" >&2
    echo "" >&2
fi

exit 0
