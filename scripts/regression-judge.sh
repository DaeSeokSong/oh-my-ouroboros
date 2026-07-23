#!/usr/bin/env bash
# regression-judge.sh — judge 기반 pass/fail 폴백 (재현 입력 없는 케이스용)
# 용도: T04 avoidance_rubric 텍스트를 기반으로 대표 task 합성 → 출력 생성 → 2차 judge 평가
#
# 사용법:
#   regression-judge.sh <rubric_file> <ruleset_dir> [--model M]
#
# exit:
#   0 = PASS (교정 규칙 미위반)
#   1 = FAIL (교정 규칙 위반 감지)
#   2 = INCONCLUSIVE (판정 불가: 파싱 실패·모델 오류)

set -uo pipefail

# ── 인자 파싱 ──────────────────────────────────────────────────────────────────
RUBRIC_FILE="${1:-}"
RULESET_DIR="${2:-}"
# 별칭 사용 — 특정 버전 하드코딩 금지 (rules/model-assignment.md 전제)
MODEL="haiku"

shift 2 2>/dev/null || true
while [[ $# -gt 0 ]]; do
    case "$1" in
        --model) MODEL="${2:-}"; shift 2 ;;
        *) echo "알 수 없는 옵션: $1" >&2; exit 2 ;;
    esac
done

# ── 입력 검증 ──────────────────────────────────────────────────────────────────
if [[ -z "$RUBRIC_FILE" || -z "$RULESET_DIR" ]]; then
    echo "사용법: regression-judge.sh <rubric_file> <ruleset_dir> [--model M]" >&2
    exit 2
fi

if [[ ! -f "$RUBRIC_FILE" ]]; then
    echo "rubric_file 미존재: $RUBRIC_FILE" >&2
    exit 2
fi

if [[ ! -d "$RULESET_DIR" ]]; then
    echo "ruleset_dir 미존재: $RULESET_DIR" >&2
    exit 2
fi

# ── experiment-gate 가드 (불변식 3) ────────────────────────────────────────────
if [[ -f "$HOME/.claude/_bench/.experiment_active" ]]; then
    echo "실험 활성 — 보류"
    exit 0
fi

# ── rubric 읽기 ────────────────────────────────────────────────────────────────
RUBRIC_TEXT=$(cat "$RUBRIC_FILE")
if [[ -z "$RUBRIC_TEXT" ]]; then
    echo "rubric_file 내용 없음: $RUBRIC_FILE" >&2
    exit 2
fi

# ── Step 1: 대표 task 합성 ──────────────────────────────────────────────────────
TASK_PROMPT="다음 교정 회피 체크리스트를 시험하기 위한 대표 작업을 한 문장으로 생성하라. 작업 문장만 출력하라(설명·이유 없이).

체크리스트:
${RUBRIC_TEXT}"

echo "── regression-judge ──────────────────────────────────"
echo "rubric: $RUBRIC_FILE"
echo "ruleset: $RULESET_DIR"
echo "model: $MODEL"
echo ""
echo "[1/3] 대표 task 합성 중..."

GENERATED_TASK=$(CLAUDE_CONFIG_DIR="$RULESET_DIR" claude -p "$TASK_PROMPT" \
    --model "$MODEL" \
    --output-format text 2>/dev/null) || {
    echo "task 합성 실패 (claude 호출 오류)" >&2
    exit 2
}

GENERATED_TASK=$(echo "$GENERATED_TASK" | head -1 | xargs)
if [[ -z "$GENERATED_TASK" ]]; then
    echo "task 합성 결과 비어 있음" >&2
    exit 2
fi

echo "합성된 task: $GENERATED_TASK"
echo ""

# ── Step 2: 합성된 task 실행 → 출력 생성 ───────────────────────────────────────
echo "[2/3] task 실행 중 (CLAUDE_CONFIG_DIR=$RULESET_DIR)..."

TASK_OUTPUT=$(CLAUDE_CONFIG_DIR="$RULESET_DIR" claude -p "$GENERATED_TASK" \
    --model "$MODEL" \
    --output-format text 2>/dev/null) || {
    echo "task 실행 실패 (claude 호출 오류)" >&2
    exit 2
}

if [[ -z "$TASK_OUTPUT" ]]; then
    echo "task 출력 비어 있음" >&2
    exit 2
fi

echo "task 출력 길이: ${#TASK_OUTPUT}자"
echo ""

# ── Step 3: 2차 judge 호출 — 규칙 위반 여부 판정 ───────────────────────────────
echo "[3/3] judge 판정 중..."

JUDGE_PROMPT="다음 출력이 아래 교정 규칙을 위반하는가? 'PASS'(미위반) 또는 'FAIL'(위반)만 답하라. 다른 텍스트 금지.

교정 규칙:
${RUBRIC_TEXT}

출력:
${TASK_OUTPUT}"

JUDGE_RESPONSE=$(claude -p "$JUDGE_PROMPT" \
    --model "$MODEL" \
    --output-format text 2>/dev/null) || {
    echo "judge 호출 실패 (claude 호출 오류)" >&2
    exit 2
}

JUDGE_VERDICT=$(echo "$JUDGE_RESPONSE" | head -1 | xargs | tr '[:lower:]' '[:upper:]')

echo ""
echo "── 결과 ──────────────────────────────────────────────"
echo "합성 task:  $GENERATED_TASK"
echo "judge 응답: $JUDGE_VERDICT"

case "$JUDGE_VERDICT" in
    PASS*)
        echo "판정: PASS — 교정 규칙 미위반"
        exit 0
        ;;
    FAIL*)
        echo "판정: FAIL — 교정 규칙 위반 감지"
        exit 1
        ;;
    *)
        echo "판정: INCONCLUSIVE — 응답 파싱 불가 ('$JUDGE_VERDICT')"
        exit 2
        ;;
esac
