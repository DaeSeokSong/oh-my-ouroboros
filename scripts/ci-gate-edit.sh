#!/usr/bin/env bash
# CI Gate: PostToolUse 후속 자동 리뷰
# Edit/Write 도구 사용 후 수정된 파일 lint 검사 + 결과 출력 (non-blocking)
# 입력: stdin JSON (tool_name + tool_input.file_path)
# 출력: stdout JSON hookSpecificOutput.additionalContext (2026-10-01 감사: 종전 stderr 는 모델에 안 닿았다)
# 종료: 항상 0 (비차단)

set -uo pipefail

INPUT=$(cat)
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
        # 2026-10-17 G6-2: 설치된 것은 markdownlint-cli2 다(종전 `markdownlint` 만 찾아 린트가 0회 실행됐다).
        # 설정은 ~/.claude/.markdownlint-cli2.jsonc(공백 양식 규칙 끔). cli2 는 배너·요약을 항상 찍으므로
        # 지적 줄(`경로:줄 error|warning MDxxx`)만 남기고 10줄로 자른다(모델 입력 보호).
        if command -v markdownlint-cli2 &>/dev/null; then
            MDL_CFG="$HOME/.claude/.markdownlint-cli2.jsonc"
            RESULT=$(markdownlint-cli2 --config "$MDL_CFG" "$FILE_PATH" 2>&1 \
                | grep -E '^[^ ]+:[0-9]+(:[0-9]+)? (error|warning) MD[0-9]{3}' | head -10)
        elif command -v markdownlint &>/dev/null; then
            RESULT=$(markdownlint "$FILE_PATH" 2>&1 | head -20)
        fi
        # 미닫힘 코드 펜스 검사는 린터 유무와 무관하게 항상 한다(markdownlint 계열은 문서 끝까지 열린 펜스를 지적하지 않는다).
        # grep -c는 무매치에도 "0"을 출력하고 exit 1 → $()안 `|| echo 0`은 "0\n0"을 만들어
        # 산술 abort(hook 실패). `||`를 밖으로 빼서 단일 숫자 보장 (2026-07-18 Codex).
        FENCE_COUNT=$(grep -c '^```' "$FILE_PATH" 2>/dev/null); FENCE_COUNT=${FENCE_COUNT:-0}
        if [ $((FENCE_COUNT % 2)) -ne 0 ]; then
            RESULT="${RESULT:+$RESULT
}⚠️ Code fence imbalance detected (count: $FENCE_COUNT)"
        fi
        ;;
    *)
        exit 0
        ;;
esac

# 결과 출력
if [ -n "$RESULT" ] && [ "$RESULT" != "All checks passed!" ]; then
    # 2026-10-01 감사: PostToolUse 의 exit 0 stderr 는 모델에 전달되지 않는다. lint 결과가 닿으려면
    # hookSpecificOutput.additionalContext JSON 이어야 한다(경고가 «닿게» 하는 수정 — 새 차단 아님, D2).
    jq -nc --arg m "🔍 [ci-gate] $FILE_PATH:
$RESULT" '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: $m}}'
fi

exit 0
