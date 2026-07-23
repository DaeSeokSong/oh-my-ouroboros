#!/usr/bin/env bash
# harness-evolve.sh — Phase 3 장기 안정성 도구 (T3.1 slow-update / T3.2 kill-switch / T3.3 zero-sum)
#
# ⚠️ 이 스크립트 전체가 QUARANTINED — P2 미배선 (2026-07-17 Codex 교차검증으로 확정).
#   훅·타이머 배선 0. 문서(learner.md·learn-from-feedback)에 수동 참조만 존재하나 learner 자동
#   플로우는 사용자 승인 경로(learner.md §step3)라 실제 호출부 없음. zerosum의 실제 자동화 역할은
#   ci-gate-commit.sh 인라인 예산 체크(AO_BUDGET)로 이미 흡수됨 — 이 서브커맨드는 미사용 중복.
#   regression-blind.sh와 동일 Phase-3 자가개선 계열 — 활성화 전 재설계 필요.
#
#   2026-07-17 수정 완료: verdict 시맨틱(INCONCLUSIVE 제외·pair 단위 n_comparable), word-split,
#   중복 case_id 감지, --model 무한루프, 개행 없는 마지막 줄(compare·killswitch), zerosum budget
#   숫자검증·10# base(leading-zero octal 방지).
#   활성화 전 잔여 하드닝(미배선이라 현 영향 0, 구조적 재설계 대상): verdict 토큰 엄격 검증,
#   suite 파일명 self-truncation 가드. (2026-07-18 Codex 추가 지적분 중 개행누락·무한루프는 수정됨)
#   가드, killswitch 지표(win_rate/reg_count) 숫자 검증, zerosum 대형 budget overflow.
#
# 서브커맨드:
#   killswitch <history_tsv>                                          G5 롤백 판정 (결정론)
#   zerosum <budget_tokens> <candidate_file> <rule_file...>           토큰 예산 점검 (결정론)
#   slowupdate-compare <prev_results_tsv> <curr_results_tsv>          회귀 비교 (결정론)
#   slowupdate-run <prev_ruleset_dir> <curr_ruleset_dir> <suite_file> [--model M]  회귀 테스트 실행
#   help                                                              도움말
#
# exit code 공통 의미:
#   killswitch:        0=OK  1=ROLLBACK  2=INSUFFICIENT
#   zerosum:           0=예산 이하  1=예산 초과(eviction 필요)
#   slowupdate-compare: 0=회귀 없음  1=회귀 발견  2=파일 불일치/빈파일
#   slowupdate-run:    0=완료(compare 결과 참조)  1=입력 오류  2=실행 불가

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ACTION="${1:-help}"

# ── [killswitch] G5 롤백 판정 ─────────────────────────────────────────────────
# 사용법: harness-evolve.sh killswitch <history_tsv>
#
# history_tsv 형식 (헤더 허용, 이후 TSV):
#   week<TAB>blind_win_rate<TAB>regression_count
#
# 판정 규칙 (결정론 — 모델 호출 없음):
#   - 최신 주 regression_count >= 1  → ROLLBACK (exit 1)
#   - 최신 2주 연속 blind_win_rate < 0.55 → ROLLBACK (exit 1)
#   - 그 외 → OK (exit 0)
#   - 유효 데이터 2주 미만 + 회귀 없음 → INSUFFICIENT (exit 2)
#
# 롤백 판정 시: 판정/제안만 출력. 자동 적용 없음 (불변식 1).
cmd_killswitch() {
    local history_tsv="${1:-}"
    if [[ -z "$history_tsv" ]]; then
        echo "사용법: harness-evolve.sh killswitch <history_tsv>" >&2
        exit 2
    fi
    if [[ ! -f "$history_tsv" ]]; then
        echo "history_tsv 미존재: $history_tsv" >&2
        exit 2
    fi

    # 헤더 스킵 후 데이터 행 파싱 (week 컬럼이 숫자가 아닌 행 = 헤더로 간주)
    local rows=()
    while IFS=$'\t' read -r week win_rate reg_count || [[ -n "$week" ]]; do   # 개행 없는 마지막 행 누락 방지 (2026-07-17 Codex)
        # 헤더 행 스킵 (week가 숫자가 아닌 경우)
        if ! [[ "$week" =~ ^[0-9] ]]; then
            continue
        fi
        rows+=("${week}|${win_rate}|${reg_count}")
    done < "$history_tsv"

    local n=${#rows[@]}

    echo "── harness-evolve killswitch ─────────────────────────"
    echo "history_tsv: $history_tsv"
    echo ""
    echo "주별 수치:"
    printf "  %-12s %-18s %-16s\n" "week" "blind_win_rate" "regression_count"
    printf "  %-12s %-18s %-16s\n" "----" "--------------" "----------------"
    for row in "${rows[@]}"; do
        IFS='|' read -r w wr rc <<< "$row"
        printf "  %-12s %-18s %-16s\n" "$w" "$wr" "$rc"
    done
    echo ""

    if [[ $n -eq 0 ]]; then
        echo "판정: INSUFFICIENT — 유효 데이터 없음"
        exit 2
    fi

    # 최신 주 (배열 마지막)
    IFS='|' read -r latest_week latest_wr latest_rc <<< "${rows[$((n-1))]}"

    # 회귀 수 정수화 (소수점 버림)
    local rc_int
    rc_int=$(echo "$latest_rc" | awk '{printf "%d", $1}')

    # 규칙 1: 최신 주 regression_count >= 1 → ROLLBACK
    if [[ "$rc_int" -ge 1 ]]; then
        echo "판정: ROLLBACK (exit 1)"
        echo "사유: 최신 주($latest_week) regression_count=${latest_rc} >= 1"
        echo ""
        echo "[제안] 사용자 승인 후 이전 ruleset_sha로 롤백 제안 (자동 적용 없음)"
        echo "       git -C ~/.claude log --oneline -5  # 이전 sha 확인"
        echo "       git -C ~/.claude checkout <sha> -- .  # 사용자가 직접 실행"
        exit 1
    fi

    # 최신 2주 데이터 확인 (규칙 2)
    if [[ $n -ge 2 ]]; then
        IFS='|' read -r prev_week prev_wr _prev_rc <<< "${rows[$((n-2))]}"

        # Python3로 float 비교 (bash 산술 불가)
        # 값은 argv로 전달 — 문자열 보간 금지 (특수문자 포함 시 파싱 깨짐 방지)
        local cond2
        cond2=$(python3 -c '
import sys

def to_float(v):
    return float(v) if v else 0.0

prev_v = to_float(sys.argv[1])
latest_v = to_float(sys.argv[2])
print("ROLLBACK" if prev_v < 0.55 and latest_v < 0.55 else "OK")
' "$prev_wr" "$latest_wr" 2>/dev/null || echo "PARSE_ERROR")

        if [[ "$cond2" == "ROLLBACK" ]]; then
            echo "판정: ROLLBACK (exit 1)"
            echo "사유: 최신 2주 연속 blind_win_rate < 0.55 (${prev_week}=${prev_wr}, ${latest_week}=${latest_wr})"
            echo ""
            echo "[제안] 사용자 승인 후 이전 ruleset_sha로 롤백 제안 (자동 적용 없음)"
            echo "       git -C ~/.claude log --oneline -5  # 이전 sha 확인"
            echo "       git -C ~/.claude checkout <sha> -- .  # 사용자가 직접 실행"
            exit 1
        elif [[ "$cond2" == "PARSE_ERROR" ]]; then
            echo "경고: blind_win_rate 파싱 실패 (값: prev=$prev_wr, latest=$latest_wr)" >&2
        fi

        echo "판정: OK (exit 0)"
        echo "사유: regression_count=0, blind_win_rate 연속 < 0.55 미충족"
        exit 0
    else
        # 데이터 1주 + 회귀 없음
        echo "판정: INSUFFICIENT (exit 2)"
        echo "사유: 유효 데이터 ${n}주 < 2주 (회귀는 없음)"
        exit 2
    fi
}

# ── [zerosum] 토큰 예산 점검 ──────────────────────────────────────────────────
# 사용법: harness-evolve.sh zerosum <budget_tokens> <candidate_file> <rule_file...>
#
# 토큰 추정: wc -m(문자수) / 4 (결정론 — 모델 호출 없음)
# budget_tokens 초과 → exit 1 + 초과량·제거 권장량 출력
# 이하 → exit 0
# 제거 대상 자동 선정 금지 — "초과 N토큰 → 제거/병합 후보 사용자 제시" 안내만 (불변식 1)
cmd_zerosum() {
    local budget_tokens="${1:-}"
    local candidate_file="${2:-}"
    shift 2 2>/dev/null || true

    if [[ -z "$budget_tokens" || -z "$candidate_file" ]]; then
        echo "사용법: harness-evolve.sh zerosum <budget_tokens> <candidate_file> <rule_file...>" >&2
        exit 1
    fi
    # budget_tokens 숫자 검증 (2026-07-17 Codex): 미검증 시 [[ -gt ]]·$(( ))가 임의 입력을 bash 산술로 평가
    if ! [[ "$budget_tokens" =~ ^[0-9]+$ ]]; then
        echo "budget_tokens는 음이 아닌 정수여야 함: $budget_tokens" >&2
        exit 1
    fi
    budget_tokens=$(( 10#$budget_tokens ))   # base-10 강제 — leading-zero(070000) octal 오류 방지 (2026-07-17 Codex)
    if [[ ! -f "$candidate_file" ]]; then
        echo "candidate_file 미존재: $candidate_file" >&2
        exit 1
    fi

    local rule_files=("$@")
    local total_rule_chars=0
    local rule_details=()

    # 각 rule_file 문자수 합산
    for rf in "${rule_files[@]}"; do
        if [[ ! -f "$rf" ]]; then
            echo "경고: rule_file 미존재(건너뜀): $rf" >&2
            continue
        fi
        local chars
        chars=$(wc -m < "$rf" 2>/dev/null || echo 0)
        total_rule_chars=$((total_rule_chars + chars))
        local tok
        tok=$(( (chars + 3) / 4 ))
        rule_details+=("  $(basename "$rf"): ${chars}자 ≈ ${tok} tokens")
    done

    local candidate_chars
    candidate_chars=$(wc -m < "$candidate_file" 2>/dev/null || echo 0)
    local candidate_tok=$(( (candidate_chars + 3) / 4 ))

    local total_chars=$((total_rule_chars + candidate_chars))
    local total_tok=$(( (total_chars + 3) / 4 ))

    echo "── harness-evolve zerosum ────────────────────────────"
    echo "예산: ${budget_tokens} tokens"
    echo ""
    echo "현재 룰 파일:"
    for d in "${rule_details[@]}"; do
        echo "$d"
    done
    local rule_tok=$(( (total_rule_chars + 3) / 4 ))
    echo "  합계: ${total_rule_chars}자 ≈ ${rule_tok} tokens"
    echo ""
    echo "후보 룰: $(basename "$candidate_file")"
    echo "  ${candidate_chars}자 ≈ ${candidate_tok} tokens"
    echo ""
    echo "합계(현재+후보): ${total_chars}자 ≈ ${total_tok} tokens"
    echo "예산:             ${budget_tokens} tokens"

    if [[ "$total_tok" -gt "$budget_tokens" ]]; then
        local excess=$(( total_tok - budget_tokens ))
        local remove_chars=$(( excess * 4 ))
        echo ""
        echo "판정: 예산 초과 (exit 1)"
        echo "초과량: ${excess} tokens (≈ ${remove_chars}자)"
        echo ""
        echo "[안내] 제거 권장량: 약 ${excess} tokens 이상 분량의 룰을 제거 또는 병합"
        echo "       제거/병합 후보 선정은 사용자가 직접 결정 (자동 선정 없음)"
        echo "       참고: 가장 최근에 추가된 룰 또는 가장 낮은 채택률 룰 우선 검토"
        exit 1
    else
        local margin=$(( budget_tokens - total_tok ))
        echo ""
        echo "판정: 예산 이하 (exit 0)"
        echo "여유: ${margin} tokens"
        exit 0
    fi
}

# ── [slowupdate-compare] 이전 vs 현재 결과 회귀 비교 ──────────────────────────
# 사용법: harness-evolve.sh slowupdate-compare <prev_results_tsv> <curr_results_tsv>
#
# 각 TSV 형식: case_id<TAB>PASS|FAIL|INCONCLUSIVE  (INCONCLUSIVE는 비교에서 제외)
# 회귀 = prev PASS → curr FAIL
# exit: 0=회귀 없음  1=회귀 발견  2=파일 불일치/빈파일 (결정론)
cmd_slowupdate_compare() {
    local prev_tsv="${1:-}"
    local curr_tsv="${2:-}"

    if [[ -z "$prev_tsv" || -z "$curr_tsv" ]]; then
        echo "사용법: harness-evolve.sh slowupdate-compare <prev_results_tsv> <curr_results_tsv>" >&2
        exit 2
    fi
    for f in "$prev_tsv" "$curr_tsv"; do
        if [[ ! -f "$f" ]]; then
            echo "파일 미존재: $f" >&2
            exit 2
        fi
        if [[ ! -s "$f" ]]; then
            echo "빈 파일: $f" >&2
            exit 2
        fi
    done

    # TSV 파싱 → associative array
    declare -A prev_map curr_map
    local prev_pass=0 prev_fail=0 curr_pass=0 curr_fail=0

    while IFS=$'\t' read -r case_id verdict || [[ -n "$case_id" ]]; do   # 개행 없는 마지막 줄 누락 방지 (2026-07-17 Codex)
        [[ -z "$case_id" ]] && continue
        if [[ -n "${prev_map[$case_id]+x}" ]]; then   # 중복 case_id는 회귀 은폐 위험 → INCONCLUSIVE (2026-07-17 Codex)
            echo "판정: INCONCLUSIVE (exit 2)"; echo "사유: prev TSV 중복 case_id ($case_id)"; exit 2
        fi
        prev_map["$case_id"]="$verdict"
        if [[ "$verdict" == "PASS" ]]; then
            ((prev_pass++)) || true
        elif [[ "$verdict" == "FAIL" ]]; then
            ((prev_fail++)) || true
        fi   # INCONCLUSIVE는 pass/fail 어느 쪽도 카운트 안 함 (제외 — map엔 남아 set-match 유지)
    done < "$prev_tsv"

    while IFS=$'\t' read -r case_id verdict || [[ -n "$case_id" ]]; do   # 개행 없는 마지막 줄 누락 방지 (prev와 대칭)
        [[ -z "$case_id" ]] && continue
        if [[ -n "${curr_map[$case_id]+x}" ]]; then   # 중복 case_id → INCONCLUSIVE (prev와 대칭, 2026-07-17 Codex)
            echo "판정: INCONCLUSIVE (exit 2)"; echo "사유: curr TSV 중복 case_id ($case_id)"; exit 2
        fi
        curr_map["$case_id"]="$verdict"
        if [[ "$verdict" == "PASS" ]]; then
            ((curr_pass++)) || true
        elif [[ "$verdict" == "FAIL" ]]; then
            ((curr_fail++)) || true
        fi   # INCONCLUSIVE 제외 (prev와 대칭)
    done < "$curr_tsv"

    # case_id 집합 일치 확인
    local prev_ids curr_ids
    prev_ids=$(printf '%s\n' "${!prev_map[@]}" | sort)
    curr_ids=$(printf '%s\n' "${!curr_map[@]}" | sort)
    if [[ "$prev_ids" != "$curr_ids" ]]; then
        echo "판정: INCONCLUSIVE (exit 2)"
        echo "사유: prev/curr case_id 집합 불일치"
        echo "  prev case 수: ${#prev_map[@]}"
        echo "  curr case 수: ${#curr_map[@]}"
        exit 2
    fi

    echo "── harness-evolve slowupdate-compare ─────────────────"
    echo "prev: $prev_tsv"
    echo "curr: $curr_tsv"
    echo ""
    printf "  %-30s %-8s %-8s %-10s\n" "case_id" "prev" "curr" "결과"
    printf "  %-30s %-8s %-8s %-10s\n" "-------" "----" "----" "----"

    local regression_cases=()
    while IFS= read -r case_id; do   # word-split 방지 (2026-07-17 Codex): 공백 포함 case_id도 안전
        local pv="${prev_map[$case_id]}"
        local cv="${curr_map[$case_id]:-MISSING}"
        local label=""
        if [[ "$pv" == "PASS" && "$cv" == "FAIL" ]]; then
            label="REGRESSION"
            regression_cases+=("$case_id")
        elif [[ "$pv" == "FAIL" && "$cv" == "PASS" ]]; then
            label="improved"
        else
            label="-"
        fi
        printf "  %-30s %-8s %-8s %-10s\n" "$case_id" "$pv" "$cv" "$label"
    done < <(printf '%s\n' "${!prev_map[@]}" | sort)

    echo ""
    echo "prev PASS: ${prev_pass} / FAIL: ${prev_fail}"
    echo "curr PASS: ${curr_pass} / FAIL: ${curr_fail}"
    echo ""

    # 비교 가능 = prev·curr 양쪽 다 PASS/FAIL인 pair (2026-07-17 Codex: prev-only 카운트는 오류 —
    # prev=PASS,curr=INCONCLUSIVE 쌍이 "회귀 없음"으로 새는 것 방지). 0이면 INCONCLUSIVE.
    local n_comparable=0
    for case_id in "${!prev_map[@]}"; do
        local pvv="${prev_map[$case_id]}" cvv="${curr_map[$case_id]:-MISSING}"
        if { [[ "$pvv" == "PASS" || "$pvv" == "FAIL" ]]; } && { [[ "$cvv" == "PASS" || "$cvv" == "FAIL" ]]; }; then
            ((n_comparable++)) || true
        fi
    done
    if [[ $n_comparable -eq 0 ]]; then
        echo "판정: INCONCLUSIVE (exit 2)"
        echo "사유: prev·curr 양쪽 결정적(PASS/FAIL)인 비교 가능 pair 0"
        exit 2
    fi

    local n_reg=${#regression_cases[@]}
    if [[ $n_reg -ge 1 ]]; then
        echo "판정: 회귀 발견 (exit 1)"
        echo "회귀 case (${n_reg}건):"
        for c in "${regression_cases[@]}"; do
            echo "  - $c"
        done
        exit 1
    else
        echo "판정: 회귀 없음 (exit 0)"
        exit 0
    fi
}

# ── [slowupdate-run] 회귀 테스트 실행 → prev/curr 결과 TSV 생성 ───────────────
# 사용법: harness-evolve.sh slowupdate-run <prev_ruleset_dir> <curr_ruleset_dir> <suite_file> [--model M]
#
# suite_file 형식: 각 행 = case_id<TAB>rubric_file (헤더 불허)
# 각 case에 대해 regression-judge.sh를 prev/curr ruleset_dir로 각각 호출
# → prev_results.tsv, curr_results.tsv 생성 (suite_file과 같은 디렉토리)
#
# ※ claude 호출 포함 — 작성만, 실행 금지.
# ※ prev_ruleset_dir 구성 참고(주석):
#   git -C ~/.claude archive <sha> | tar -x -C <prev_ruleset_dir>
#
# exit: 0=완료(결과 파일 생성, compare로 회귀 확인)  1=입력 오류  2=실행 불가
cmd_slowupdate_run() {
    local prev_ruleset_dir="${1:-}"
    local curr_ruleset_dir="${2:-}"
    local suite_file="${3:-}"
    local model="haiku"  # 별칭 — 특정 버전 하드코딩 금지

    shift 3 2>/dev/null || true
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --model)
                [[ -z "${2:-}" ]] && { echo "--model 값 필요" >&2; exit 1; }  # 값 없으면 shift 2 실패로 무한루프 (2026-07-17 Codex)
                model="$2"; shift 2 ;;
            *) echo "알 수 없는 옵션: $1" >&2; exit 1 ;;
        esac
    done

    if [[ -z "$prev_ruleset_dir" || -z "$curr_ruleset_dir" || -z "$suite_file" ]]; then
        echo "사용법: harness-evolve.sh slowupdate-run <prev_ruleset_dir> <curr_ruleset_dir> <suite_file> [--model M]" >&2
        exit 1
    fi
    for d in "$prev_ruleset_dir" "$curr_ruleset_dir"; do
        if [[ ! -d "$d" ]]; then
            echo "ruleset_dir 미존재: $d" >&2
            exit 1
        fi
    done
    if [[ ! -f "$suite_file" ]]; then
        echo "suite_file 미존재: $suite_file" >&2
        exit 1
    fi

    # experiment-gate 가드 (불변식 — 실험 활성 중 실행 금지)
    if [[ -f "$HOME/.claude/_bench/.experiment_active" ]]; then
        echo "실험 활성 — slowupdate-run 보류 (experiment-gate)"
        exit 0
    fi

    local judge_script="$SCRIPT_DIR/regression-judge.sh"
    if [[ ! -f "$judge_script" ]]; then
        echo "regression-judge.sh 미존재: $judge_script" >&2
        exit 2
    fi

    local suite_dir
    suite_dir="$(dirname "$suite_file")"
    local prev_out="$suite_dir/prev_results.tsv"
    local curr_out="$suite_dir/curr_results.tsv"

    # 결과 파일 초기화
    : > "$prev_out"
    : > "$curr_out"

    # judge_script 출력 캡처용 임시 파일 (PID 재사용/충돌 방지 — mktemp)
    local prev_log curr_log
    prev_log="$(mktemp)" || { echo "임시 파일 생성 실패" >&2; exit 2; }
    curr_log="$(mktemp)" || { echo "임시 파일 생성 실패" >&2; exit 2; }

    echo "── harness-evolve slowupdate-run ─────────────────────"
    echo "prev_ruleset: $prev_ruleset_dir"
    echo "curr_ruleset: $curr_ruleset_dir"
    echo "suite_file:   $suite_file"
    echo "model:        $model"
    echo ""
    echo "# prev_ruleset_dir 구성 참고 (git 이전 sha checkout):"
    echo "#   sha=<이전 ruleset sha>  # git -C ~/.claude log --oneline -10"
    echo "#   git -C ~/.claude archive \$sha | tar -x -C $prev_ruleset_dir"
    echo ""

    local case_num=0
    while IFS=$'\t' read -r case_id rubric_file || [[ -n "$case_id" ]]; do   # 개행 없는 마지막 행 누락 방지 (2026-07-18 Codex)
        [[ -z "$case_id" ]] && continue
        ((case_num++)) || true

        echo "[case $case_num] $case_id"
        echo "  rubric: $rubric_file"

        # rubric_file이 상대경로인 경우 suite_dir 기준 해석
        if [[ ! "$rubric_file" = /* ]]; then
            rubric_file="$suite_dir/$rubric_file"
        fi
        if [[ ! -f "$rubric_file" ]]; then
            echo "  경고: rubric_file 미존재, INCONCLUSIVE로 기록" >&2
            printf '%s\t%s\n' "$case_id" "INCONCLUSIVE" >> "$prev_out"
            printf '%s\t%s\n' "$case_id" "INCONCLUSIVE" >> "$curr_out"
            continue
        fi

        # prev ruleset 실행
        local prev_exit=0
        bash "$judge_script" "$rubric_file" "$prev_ruleset_dir" --model "$model" \
            > "$prev_log" 2>&1 || prev_exit=$?
        local prev_verdict="INCONCLUSIVE"   # 기본 = INCONCLUSIVE — 예상 못한 exit(인프라 오류)가 허위 회귀로 둔갑하지 않게 (2026-07-17 Codex C3)
        if [[ $prev_exit -eq 0 ]]; then
            prev_verdict="PASS"
        elif [[ $prev_exit -eq 1 ]]; then
            prev_verdict="FAIL"
        fi   # exit 2 및 그 외 = INCONCLUSIVE(기본값 유지) → 비교에서 제외
        printf '%s\t%s\n' "$case_id" "$prev_verdict" >> "$prev_out"
        echo "  prev → $prev_verdict (exit $prev_exit)"

        # curr ruleset 실행
        local curr_exit=0
        bash "$judge_script" "$rubric_file" "$curr_ruleset_dir" --model "$model" \
            > "$curr_log" 2>&1 || curr_exit=$?
        local curr_verdict="INCONCLUSIVE"   # 기본 = INCONCLUSIVE (prev와 대칭 — 2026-07-17 Codex C3)
        if [[ $curr_exit -eq 0 ]]; then
            curr_verdict="PASS"
        elif [[ $curr_exit -eq 1 ]]; then
            curr_verdict="FAIL"
        fi   # exit 2 및 그 외 = INCONCLUSIVE → 비교에서 제외
        printf '%s\t%s\n' "$case_id" "$curr_verdict" >> "$curr_out"
        echo "  curr → $curr_verdict (exit $curr_exit)"
        echo ""
    done < "$suite_file"

    # 임시 파일 정리
    rm -f "$prev_log" "$curr_log"

    if [[ $case_num -eq 0 ]]; then
        echo "경고: suite_file에 유효한 case 없음" >&2
        exit 2
    fi

    echo "완료: $case_num 개 case 처리"
    echo "결과 파일:"
    echo "  prev: $prev_out"
    echo "  curr: $curr_out"
    echo ""
    echo "다음 단계: slowupdate-compare로 회귀 점검"
    echo "  harness-evolve.sh slowupdate-compare $prev_out $curr_out"
    exit 0
}

# ── 서브커맨드 라우팅 ─────────────────────────────────────────────────────────
case "$ACTION" in
    killswitch)
        shift
        cmd_killswitch "$@"
        ;;
    zerosum)
        shift
        cmd_zerosum "$@"
        ;;
    slowupdate-compare)
        shift
        cmd_slowupdate_compare "$@"
        ;;
    slowupdate-run)
        shift
        cmd_slowupdate_run "$@"
        ;;
    help|*)
        cat <<'HELP'
harness-evolve.sh — Phase 3 장기 안정성 도구

서브커맨드:
  killswitch <history_tsv>
      G5 롤백 판정 (결정론). history_tsv: week<TAB>blind_win_rate<TAB>regression_count
      exit: 0=OK  1=ROLLBACK  2=INSUFFICIENT(데이터 부족)

  zerosum <budget_tokens> <candidate_file> <rule_file...>
      토큰 예산 점검 (결정론). wc -m / 4 로 토큰 추정.
      exit: 0=예산 이하  1=예산 초과(eviction 필요)

  slowupdate-compare <prev_results_tsv> <curr_results_tsv>
      prev vs curr 회귀 비교 (결정론). 각 TSV: case_id<TAB>PASS|FAIL|INCONCLUSIVE (INCONCLUSIVE 제외)
      exit: 0=회귀 없음  1=회귀 발견  2=파일 불일치/빈파일

  slowupdate-run <prev_ruleset_dir> <curr_ruleset_dir> <suite_file> [--model M]
      회귀 테스트 실행. suite_file: case_id<TAB>rubric_file
      prev/curr_results.tsv 생성 후 slowupdate-compare로 점검.
      exit: 0=완료  1=입력 오류  2=실행 불가

  help
      이 도움말 출력

주의: 모든 판정/제안은 사용자 승인 후 적용. 자동 롤백·자동 제거 없음.
HELP
        ;;
esac
