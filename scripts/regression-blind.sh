#!/usr/bin/env bash
# regression-blind.sh — Tier-2 blind A/B 채택 게이트
# 3 서브커맨드: prepare / run / verdict
#
# ⚠️ QUARANTINED — P2 미배선, 활성화 전 재설계 필수 (2026-07-17 Codex 교차검증)
#   현재 설계는 blind-by-construction이 아니다. 활성화(learner 자동 연결) 전 아래 결함 해소 필요:
#   1) verdict가 정답 키(type·new_label)를 판정자의 picks_file에서 읽는다(cmd_verdict) —
#      판정자가 정답을 보며 고르는 구조. → picks는 (trial_idx·pick·sec)만 받고, type·new_label은
#      held-aside key.tsv에서 join하도록 verdict 인터페이스 재설계 필요.
#   2) trial 순서가 real→catch 고정(셔플 없음) → 순서·개수로 catch 위치 추론 가능. → 셔플 후 기록.
#   현 상태에서 자동 채택 게이트로 사용 금지. learner는 사용자 승인 경로 사용(learner.md § step 3).
#   판정 파일 헤더·리스팅의 real/catch 라벨 누출은 2026-07-17 봉인 완료(부분 개선).
#
# 사용법:
#   regression-blind.sh prepare <candidate_edit_file> <work_dir>
#   regression-blind.sh run <work_dir> <suite_file> [--model M] [--catch N]
#   regression-blind.sh verdict <picks_file>
#
# verdict exit:
#   0 = ACCEPT
#   1 = REJECT
#   2 = INCONCLUSIVE

set -uo pipefail

BENCH_DIR="$HOME/.claude/_bench"
mkdir -p "$BENCH_DIR"

ACTION="${1:-help}"
shift 1 || true

# ── helpers ────────────────────────────────────────────────────────────────────

_experiment_gate() {
    if [[ -f "$HOME/.claude/_bench/.experiment_active" ]]; then
        echo "실험 활성 — 보류"
        exit 0
    fi
}

# settings.json에서 hooks 제거 (jq 우선, python3 폴백)
_remove_hooks() {
    local settings_file="$1"
    [[ ! -f "$settings_file" ]] && return 0
    if command -v jq &>/dev/null; then
        local tmp
        tmp=$(jq 'del(.hooks)' "$settings_file" 2>/dev/null) && echo "$tmp" > "$settings_file"
    else
        python3 - "$settings_file" <<'PYEOF'
import json, sys
p = sys.argv[1]
try:
    with open(p) as f:
        d = json.load(f)
    d.pop("hooks", None)
    with open(p, "w") as f:
        json.dump(d, f, indent=2)
except Exception as e:
    print(f"hooks 제거 실패(python3): {e}", file=sys.stderr)
PYEOF
    fi
}

# rsync 우선, cp -a 폴백으로 디렉토리 경량 복사
_copy_claude_dir() {
    local src="$1" dst="$2"
    mkdir -p "$dst"
    if command -v rsync &>/dev/null; then
        rsync -a \
            --exclude='projects' \
            --exclude='jobs' \
            --exclude='_bench' \
            --exclude='shell-snapshots' \
            --exclude='todos' \
            --exclude='statsig' \
            --exclude='history.jsonl' \
            --exclude='file-history' \
            --exclude='worktrees' \
            --exclude='teams' \
            --exclude='logs' \
            --exclude='.git' \
            --exclude='downloads' \
            --exclude='ide' \
            "$src/" "$dst/"
    else
        # cp -a 폴백: 전체 복사 후 무거운 폴더만 제거
        cp -a "$src/." "$dst/"
        for excl in projects jobs _bench shell-snapshots todos statsig \
                    file-history worktrees teams logs .git downloads ide; do
            rm -rf "${dst:?}/$excl" 2>/dev/null || true
        done
        # history.jsonl 파일 제거
        rm -f "${dst:?}/history.jsonl" 2>/dev/null || true
    fi
}

# ── prepare ────────────────────────────────────────────────────────────────────
cmd_prepare() {
    local candidate_edit_file="${1:-}"
    local work_dir="${2:-}"

    if [[ -z "$candidate_edit_file" || -z "$work_dir" ]]; then
        echo "사용법: regression-blind.sh prepare <candidate_edit_file> <work_dir>" >&2
        exit 2
    fi
    if [[ ! -f "$candidate_edit_file" ]]; then
        echo "candidate_edit_file 미존재: $candidate_edit_file" >&2
        exit 2
    fi

    _experiment_gate

    local old_dir="$work_dir/ruleset_old"
    local new_dir="$work_dir/ruleset_new"

    echo "── regression-blind prepare ──────────────────────────"
    echo "candidate: $candidate_edit_file"
    echo "work_dir:  $work_dir"
    echo ""

    # ruleset_old 복사
    echo "[1/4] ruleset_old 복사 중..."
    _copy_claude_dir "$HOME/.claude" "$old_dir"

    # ruleset_new 복사
    echo "[2/4] ruleset_new 복사 중..."
    _copy_claude_dir "$HOME/.claude" "$new_dir"

    # ruleset_new에 후보 룰 append (원본 CLAUDE.md 불변)
    echo "[3/4] 후보 룰 적용 (ruleset_new/CLAUDE.md append)..."
    local new_claude_md="$new_dir/CLAUDE.md"
    if [[ -f "$new_claude_md" ]]; then
        printf "\n\n## [Candidate Rule — regression-blind]\n" >> "$new_claude_md"
        cat "$candidate_edit_file" >> "$new_claude_md"
    else
        echo "경고: $new_claude_md 미존재 — 후보 룰을 신규 파일로 생성" >&2
        cat "$candidate_edit_file" > "$new_claude_md"
    fi

    # 양쪽 settings.json hooks 제거 (부작용 차단)
    echo "[4/4] settings.json hooks 제거..."
    _remove_hooks "$old_dir/settings.json"
    _remove_hooks "$new_dir/settings.json"

    echo ""
    echo "── 준비 완료 ─────────────────────────────────────────"
    echo "OLD: $old_dir"
    echo "NEW: $new_dir"
}

# ── run ────────────────────────────────────────────────────────────────────────
cmd_run() {
    local work_dir="${1:-}"
    local suite_file="${2:-}"
    local MODEL="haiku"  # 별칭 — 특정 버전 하드코딩 금지
    local CATCH_N=2
    shift 2 2>/dev/null || true

    while [[ $# -gt 0 ]]; do
        case "$1" in
            # 값 없음 방어 (2026-07-18 Codex): shift 2가 인자 1개 남을 때 실패해 무한루프
            --model)
                [[ -z "${2:-}" ]] && { echo "--model 값 필요" >&2; exit 2; }
                MODEL="$2"; shift 2 ;;
            --catch)
                [[ -z "${2:-}" ]] && { echo "--catch 값 필요" >&2; exit 2; }
                # 숫자 검증 + 최소 1 (catch=0은 attention-check 무력화 → blind 게이트 우회)
                [[ "$2" =~ ^[0-9]+$ ]] || { echo "--catch는 양의 정수" >&2; exit 2; }
                [ "$2" -lt 1 ] && { echo "--catch는 1 이상 (0은 catch trial 없어 게이트 우회)" >&2; exit 2; }
                CATCH_N="$2"; shift 2 ;;
            *) echo "알 수 없는 옵션: $1" >&2; exit 2 ;;
        esac
    done

    if [[ -z "$work_dir" || -z "$suite_file" ]]; then
        echo "사용법: regression-blind.sh run <work_dir> <suite_file> [--model M] [--catch N]" >&2
        exit 2
    fi

    _experiment_gate

    local old_dir="$work_dir/ruleset_old"
    local new_dir="$work_dir/ruleset_new"

    if [[ ! -d "$old_dir" || ! -d "$new_dir" ]]; then
        echo "prepare 미실행: $old_dir 또는 $new_dir 미존재" >&2
        exit 2
    fi
    if [[ ! -f "$suite_file" ]]; then
        echo "suite_file 미존재: $suite_file" >&2
        exit 2
    fi

    local pairs_dir="$work_dir/pairs"
    local key_tsv="$work_dir/key.tsv"
    mkdir -p "$pairs_dir"

    # key.tsv 헤더
    echo -e "trial_idx\ttype\tnew_label" > "$key_tsv"

    echo "── regression-blind run ──────────────────────────────"
    echo "work_dir:  $work_dir"
    echo "suite:     $suite_file"
    echo "model:     $MODEL"
    echo "catch_N:   $CATCH_N"
    echo ""
    echo "※ 주의: 이 서브커맨드는 claude 모델 호출을 포함합니다."
    echo "   실제 실행 전 사용자가 직접 수행하세요."
    echo ""

    # task 목록 읽기 (빈 줄·# 주석 제외)
    mapfile -t TASKS < <(grep -v '^[[:space:]]*$\|^#' "$suite_file")
    local real_count=${#TASKS[@]}

    if [[ "$real_count" -eq 0 ]]; then
        echo "suite_file에 유효한 task 없음" >&2
        exit 2
    fi

    echo "[실행] real trials: $real_count, catch trials: $CATCH_N"
    echo ""

    local idx=0

    # real trials
    for task in "${TASKS[@]}"; do
        local t_start
        t_start=$(date +%s)

        echo "[trial $idx] task: ${task:0:60}..."

        local out_old out_new
        out_old=$(CLAUDE_CONFIG_DIR="$old_dir" claude -p "$task" \
            --model "$MODEL" --output-format text 2>/dev/null) || out_old="(오류)"
        out_new=$(CLAUDE_CONFIG_DIR="$new_dir" claude -p "$task" \
            --model "$MODEL" --output-format text 2>/dev/null) || out_new="(오류)"

        # 라벨 랜덤 셔플 (A/B 어느 쪽이 new인지 숨김)
        # new_label은 new 콘텐츠가 실제로 들어간 라벨과 일치해야 함 (verdict W 계산의 정확성)
        local new_label="B"               # 기본: A=old, B=new → new는 B
        local label_a_content="$out_old"
        local label_b_content="$out_new"
        local coin=$(( RANDOM % 2 ))
        if [[ "$coin" -eq 1 ]]; then
            new_label="A"                 # 셔플: A=new, B=old → new는 A
            label_a_content="$out_new"
            label_b_content="$out_old"
        fi

        # pairs/<idx>.txt 저장
        {
            echo "=== Trial $idx ==="
            echo "Task: $task"
            echo ""
            echo "--- Response A ---"
            echo "$label_a_content"
            echo ""
            echo "--- Response B ---"
            echo "$label_b_content"
        } > "$pairs_dir/${idx}.txt"

        # key.tsv 기록 (사용자에게 안 보임)
        printf "%s\treal\t%s\n" "$idx" "$new_label" >> "$key_tsv"

        idx=$(( idx + 1 ))
        # 블라인드 유지 (2026-07-17 Codex C3): new_label을 stdout에 노출하지 않는다 — 운영자 편향 방지. key_tsv에만 보존.
        echo "  → trial $((idx-1)) 저장 완료 (파일: pairs/$((idx-1)).txt)"
    done

    # catch trials — old 출력을 양쪽 동일하게 삽입
    for (( c=0; c<CATCH_N; c++ )); do
        local catch_task_idx=$(( RANDOM % real_count ))
        local catch_task="${TASKS[$catch_task_idx]}"

        echo "[trial $idx] task: ${catch_task:0:60}..."

        local out_catch
        out_catch=$(CLAUDE_CONFIG_DIR="$old_dir" claude -p "$catch_task" \
            --model "$MODEL" --output-format text 2>/dev/null) || out_catch="(오류)"

        {
            echo "=== Trial $idx ==="
            echo "Task: $catch_task"
            echo ""
            echo "--- Response A ---"
            echo "$out_catch"
            echo ""
            echo "--- Response B ---"
            echo "$out_catch"
        } > "$pairs_dir/${idx}.txt"

        # catch: new_label=none (정답=same, A≡B)
        printf "%s\tcatch\tnone\n" "$idx" >> "$key_tsv"

        idx=$(( idx + 1 ))
        echo "  → catch trial $((idx-1)) 저장 완료"
    done

    echo ""
    echo "── 생성 완료 ─────────────────────────────────────────"
    echo "총 trials: $idx (real=$real_count, catch=$CATCH_N)"
    echo "pairs 위치: $pairs_dir/"
    echo ""
    echo "── 사용자 안내 ───────────────────────────────────────"
    echo "아래 파일들을 순서대로 열어 각 trial의 A/B 중 더 나은 응답을 선택하세요."
    echo "(catch trial은 A≡B — 구별 불가 시 'same' 입력)"
    echo ""
    # 블라인드 유지 (2026-07-17 Codex C3): trial 타입(real/catch)을 판정자 리스팅에 노출하지 않는다 — key_tsv에만 보존
    for (( i=0; i<idx; i++ )); do
        echo "  trial $i: $pairs_dir/${i}.txt"
    done
    echo ""
    echo "picks_file 형식(TSV — verdict에 전달):"
    echo "  trial_idx<TAB>type<TAB>user_pick(A|B|same)<TAB>new_label<TAB>response_sec"
    echo "  예: 0\treal\tA\tA\t5"
    echo ""
    echo "verdict 실행:"
    echo "  regression-blind.sh verdict <picks_file>"
}

# ── verdict ────────────────────────────────────────────────────────────────────
# 모델 호출 없음 — 결정론적
cmd_verdict() {
    local picks_file="${1:-}"

    if [[ -z "$picks_file" ]]; then
        echo "사용법: regression-blind.sh verdict <picks_file>" >&2
        exit 2
    fi
    if [[ ! -f "$picks_file" ]]; then
        echo "picks_file 미존재: $picks_file" >&2
        exit 2
    fi

    echo "── regression-blind verdict ──────────────────────────"
    echo "picks: $picks_file"
    echo ""

    # TSV 파싱 + 통계 계산 (python3 — bash 산술 부동소수점 한계 회피)
    python3 - "$picks_file" <<'PYEOF'
import sys, math

picks_file = sys.argv[1]

trials = []
with open(picks_file) as f:
    for line in f:
        line = line.rstrip("\n")
        if not line or line.startswith("trial_idx"):  # header skip
            continue
        parts = line.split("\t")
        if len(parts) < 5:
            # response_sec 없으면 999 기본값
            parts.extend(["999"] * (5 - len(parts)))
        trial_idx = parts[0].strip()
        ttype = parts[1].strip()       # real | catch
        user_pick = parts[2].strip()   # A | B | same
        new_label = parts[3].strip()   # A | B | none
        try:
            response_sec = float(parts[4].strip())
        except ValueError:
            response_sec = 999.0
        trials.append({
            "idx": trial_idx,
            "type": ttype,
            "user_pick": user_pick,
            "new_label": new_label,
            "response_sec": response_sec,
        })

if not trials:
    print("picks_file에 유효한 trial 없음")
    sys.exit(2)

# ── catch 평가 ──────────────────────────────────────────────
catch_trials = [t for t in trials if t["type"] == "catch"]
if catch_trials:
    catch_pass = sum(1 for t in catch_trials if t["user_pick"] == "same")
    catch_pass_rate = catch_pass / len(catch_trials)
else:
    catch_pass_rate = 1.0  # catch 없으면 패스로 처리

# ── rubber-stamp 필터 ─────────────────────────────────────────
# 조건1: response_sec < 2 인 real trial 제외
# 조건2: 연속 5개 동일 pick real trial 제외
real_trials = [t for t in trials if t["type"] == "real"]

# response_sec < 2 제외
filtered = [t for t in real_trials if t["response_sec"] >= 2.0]

# 5연속 동일 pick 감지 → 해당 구간 제외
def remove_consecutive_runs(trials, run_len=5):
    if len(trials) < run_len:
        return trials
    result = []
    i = 0
    while i < len(trials):
        # i부터 run_len개 모두 동일 pick인지 확인
        if i + run_len <= len(trials):
            window = [t["user_pick"] for t in trials[i:i+run_len]]
            if len(set(window)) == 1:
                # 연속 run 전체 제외 후 다음 구간으로
                i += run_len
                continue
        result.append(trials[i])
        i += 1
    return result

filtered = remove_consecutive_runs(filtered, run_len=5)

# ── real 승률 계산 ────────────────────────────────────────────
# same 선택은 유효 판정에서 제외
valid_real = [t for t in filtered if t["user_pick"] in ("A", "B")]
N = len(valid_real)
W = sum(1 for t in valid_real if t["user_pick"] == t["new_label"])

# ── 부호검정 p-value (one-sided, N>0) ─────────────────────────
if N > 0:
    p_value = sum(math.comb(N, k) for k in range(W, N + 1)) / (2 ** N)
    win_rate = W / N
else:
    p_value = 1.0
    win_rate = 0.0

# ── 출력 ──────────────────────────────────────────────────────
print(f"catch trials:      {len(catch_trials)}건 / pass: {catch_pass if catch_trials else 'N/A'}")
print(f"catch_pass_rate:   {catch_pass_rate:.2f}")
print(f"real trials(raw):  {len(real_trials)}건")
print(f"rubber-stamp 제외: {len(real_trials) - len(filtered)}건")
print(f"유효 real trials:  {N}건 (same 제외)")
print(f"W (신규룰 선택):   {W}건")
print(f"승률 (W/N):        {win_rate:.2f}")
print(f"p-value (one-sid): {p_value:.4f}")
print()

# ── 판정 ──────────────────────────────────────────────────────
# ACCEPT: catch_pass_rate≥0.80 AND N>0 AND W/N≥0.60 AND p<0.05
# INCONCLUSIVE: catch<0.80 OR N<1
# REJECT: 그 외

if catch_pass_rate < 0.80 or N < 1:
    verdict = "INCONCLUSIVE"
    print(f"판정: INCONCLUSIVE")
    if catch_pass_rate < 0.80:
        print(f"  사유: catch_pass_rate({catch_pass_rate:.2f}) < 0.80 — 사용자 집중도 부족")
    if N < 1:
        print(f"  사유: 유효 real trial 0건")
    sys.exit(2)
elif win_rate >= 0.60 and p_value < 0.05:
    verdict = "ACCEPT"
    print(f"판정: ACCEPT — 신규 룰 채택 권장")
    print(f"  (승률 {win_rate:.0%} ≥ 60%, p={p_value:.4f} < 0.05)")
    print()
    print("※ 실제 룰 Edit는 사용자 승인 후 수행 (blind 선택=승인)")
    sys.exit(0)
else:
    verdict = "REJECT"
    print(f"판정: REJECT — 신규 룰 채택 기준 미충족")
    if win_rate < 0.60:
        print(f"  사유: 승률({win_rate:.0%}) < 60%")
    if p_value >= 0.05:
        print(f"  사유: p-value({p_value:.4f}) ≥ 0.05")
    sys.exit(1)
PYEOF
    local py_exit=$?
    exit $py_exit
}

# ── 서브커맨드 라우팅 ───────────────────────────────────────────────────────────
case "$ACTION" in
    prepare)
        cmd_prepare "$@"
        ;;
    run)
        cmd_run "$@"
        ;;
    verdict)
        cmd_verdict "$@"
        ;;
    help|*)
        cat <<'HELP'
regression-blind.sh — Tier-2 blind A/B 채택 게이트

사용법:
  regression-blind.sh prepare <candidate_edit_file> <work_dir>
      후보 룰 적용 전/후 ruleset sandbox 생성

  regression-blind.sh run <work_dir> <suite_file> [--model M] [--catch N]
      각 task에 대해 old/new 출력 쌍 생성 (A/B 라벨 랜덤 셔플)
      기본값: --model haiku --catch 2
      ※ claude 모델 호출 포함 — 사용자가 직접 실행

  regression-blind.sh verdict <picks_file>
      사용자 선택 결과(TSV) 분석 → ACCEPT/REJECT/INCONCLUSIVE
      picks_file TSV: trial_idx<TAB>type<TAB>user_pick<TAB>new_label<TAB>response_sec
      모델 호출 없음 — 결정론적

판정 기준 (ACCEPT):
  catch_pass_rate ≥ 0.80 AND W/N ≥ 0.60 AND p(one-sided) < 0.05

exit: 0=ACCEPT, 1=REJECT, 2=INCONCLUSIVE
HELP
        ;;
esac
