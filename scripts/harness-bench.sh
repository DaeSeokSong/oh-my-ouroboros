#!/usr/bin/env bash
# Harness Bench: Before/After 측정
# 룰/스킬 변경 전후 동일 작업을 실행하여 효과 비교
# 사용법:
#   harness-bench.sh init "작업 설명" "벤치 ID"     - 측정 환경 초기화
#   harness-bench.sh before "벤치 ID" "결과 요약"  - Before 결과 기록
#   harness-bench.sh after "벤치 ID" "결과 요약"   - After 결과 기록 + 비교 보고
#   harness-bench.sh gate "벤치 ID"                - Pareto gate 판정 (exit 0=개선, 1=미개선, 2=inconclusive)
#   harness-bench.sh report "벤치 ID"              - 측정 결과 조회
#   harness-bench.sh list                           - 모든 벤치 목록

set -uo pipefail

BENCH_DIR="$HOME/.claude/_bench"
mkdir -p "$BENCH_DIR"

ACTION="${1:-help}"

# 사용 마커 — harness-usage-check.sh의 BENCH_PENDING/STALE 판정 기준점.
# EXIT trap인 이유: gate 등 일부 arm이 중간 exit하므로 파일 끝 배치로는 안 찍힘 (Codex 교차검증 P2).
# help/무인자 호출은 실사용이 아니므로 마커를 찍지 않는다 (찍으면 미사용 상태가 가려짐).
case "$ACTION" in
    init|before|after|gate|report)
        trap 'mkdir -p "$HOME/.claude/_usage" 2>/dev/null; touch "$HOME/.claude/_usage/bench-last" 2>/dev/null' EXIT
        ;;
esac

case "$ACTION" in
    init)
        DESC="${2:-}"
        BENCH_ID="${3:-bench-$(date +%Y%m%d-%H%M%S)}"
        BENCH_FILE="$BENCH_DIR/$BENCH_ID.md"
        if [ -f "$BENCH_FILE" ]; then
            echo "❌ 벤치 ID '$BENCH_ID' 이미 존재" >&2
            exit 1
        fi
        cat > "$BENCH_FILE" <<EOF
# Harness Bench: $BENCH_ID

- **작업 설명**: $DESC
- **초기화**: $(date -Iseconds)
- **상태**: 측정 대기

## Before
(미측정)

## After
(미측정)

## Gate 판정
(미산출)

## 비교 결과
(미산출)
EOF
        echo "✅ 벤치 초기화: $BENCH_FILE"
        ;;
    before|after)
        BENCH_ID="${2:-}"
        SUMMARY="${3:-}"
        BENCH_FILE="$BENCH_DIR/$BENCH_ID.md"
        [ ! -f "$BENCH_FILE" ] && { echo "❌ 벤치 ID '$BENCH_ID' 미존재" >&2; exit 1; }
        TIMESTAMP=$(date -Iseconds)
        # 임시 파일로 ## Before 또는 ## After 섹션 갱신
        SECTION="## ${ACTION^}"  # ## Before 또는 ## After
        awk -v sec="$SECTION" -v ts="$TIMESTAMP" -v sum="$SUMMARY" '
            $0 == sec { print; print "- **시각**: " ts; print "- **결과**: " sum; skip=1; next }
            skip && /^## / { skip=0 }
            !skip { print }
        ' "$BENCH_FILE" > "$BENCH_FILE.tmp" && mv "$BENCH_FILE.tmp" "$BENCH_FILE"
        echo "✅ $ACTION 기록: $BENCH_FILE"
        if [ "$ACTION" = "after" ]; then
            echo ""
            echo "📊 비교 보고:"
            echo "  Before: $(grep -A1 '^## Before' "$BENCH_FILE" | tail -1)"
            echo "  After:  $(grep -A1 '^## After' "$BENCH_FILE" | tail -1)"
        fi
        ;;
    gate)
        BENCH_ID="${2:-}"
        BENCH_FILE="$BENCH_DIR/$BENCH_ID.md"
        [ ! -f "$BENCH_FILE" ] && { echo "❌ 벤치 ID '$BENCH_ID' 미존재" >&2; exit 1; }

        # Before/After 섹션에서 key=value 파싱 (awk)
        parse_section() {
            local file="$1" section="$2" key="$3"
            awk -v sec="$section" -v k="$key" '
                $0 == sec { in_sec=1; next }
                in_sec && /^## / { in_sec=0 }
                in_sec { for(i=1;i<=NF;i++) { if($i ~ "^"k"=[0-9]+$") { split($i,a,"="); print a[2]; exit } } }
            ' "$file"
        }

        # 게이트 대상 metric: attempts, interventions, qa_fail (tokens: 모니터 전용)
        B_ATT=$(parse_section "$BENCH_FILE" "## Before" "attempts")
        B_INT=$(parse_section "$BENCH_FILE" "## Before" "interventions")
        B_QAF=$(parse_section "$BENCH_FILE" "## Before" "qa_fail")
        B_TOK=$(parse_section "$BENCH_FILE" "## Before" "tokens")

        A_ATT=$(parse_section "$BENCH_FILE" "## After" "attempts")
        A_INT=$(parse_section "$BENCH_FILE" "## After" "interventions")
        A_QAF=$(parse_section "$BENCH_FILE" "## After" "qa_fail")
        A_TOK=$(parse_section "$BENCH_FILE" "## After" "tokens")

        # 게이트 metric 누락 시 exit 2 (inconclusive)
        MISSING=0
        for val in "$B_ATT" "$B_INT" "$B_QAF" "$A_ATT" "$A_INT" "$A_QAF"; do
            [ -z "$val" ] && MISSING=1
        done
        if [ "$MISSING" -eq 1 ]; then
            echo "⚠️  gate inconclusive: 게이트 metric(attempts/interventions/qa_fail) 누락"
            echo "   Before section에 'attempts=N interventions=N qa_fail=N' 형식 필요"
            exit 2
        fi

        # 각 metric 출력 (tokens는 모니터 전용 — 판정 제외)
        echo "📊 Gate 판정 결과:"
        echo "  attempts:      ${B_ATT} → ${A_ATT}"
        echo "  interventions: ${B_INT} → ${A_INT}"
        echo "  qa_fail:       ${B_QAF} → ${A_QAF}"
        [ -n "$B_TOK" ] || B_TOK="(미기록)"
        [ -n "$A_TOK" ] || A_TOK="(미기록)"
        echo "  tokens (모니터 전용, 게이트 제외): ${B_TOK} → ${A_TOK}"

        # Pareto strict improvement 판정
        # 조건1: 모든 게이트 metric에서 after ≤ before (악화 없음)
        # 조건2: 적어도 하나의 게이트 metric에서 after < before (엄격 개선)
        REGRESSION=0
        IMPROVED=0
        for pair in "${B_ATT}:${A_ATT}" "${B_INT}:${A_INT}" "${B_QAF}:${A_QAF}"; do
            bv="${pair%%:*}"
            av="${pair##*:}"
            [ "$av" -gt "$bv" ] 2>/dev/null && REGRESSION=1
            [ "$av" -lt "$bv" ] 2>/dev/null && IMPROVED=1
        done

        if [ "$REGRESSION" -eq 1 ]; then
            echo "  판정: ❌ FAIL — 게이트 metric 악화 (exit 1)"
            exit 1
        elif [ "$IMPROVED" -eq 1 ]; then
            echo "  판정: ✅ PASS — Pareto strict improvement (exit 0)"
            exit 0
        else
            echo "  판정: ⚠️  동점 — 개선 없음 (exit 1)"
            exit 1
        fi
        ;;
    report)
        BENCH_ID="${2:-}"
        BENCH_FILE="$BENCH_DIR/$BENCH_ID.md"
        [ ! -f "$BENCH_FILE" ] && { echo "❌ 벤치 ID '$BENCH_ID' 미존재" >&2; exit 1; }
        cat "$BENCH_FILE"
        ;;
    list)
        echo "📋 등록된 벤치:"
        ls -1 "$BENCH_DIR"/*.md 2>/dev/null | xargs -I{} basename {} .md | sed 's/^/  - /'
        ;;
    help|*)
        sed -n '2,9p' "$0"
        ;;
esac
