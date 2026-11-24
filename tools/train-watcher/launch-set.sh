#!/usr/bin/env bash
# launch-set.sh — 학습 발사 2종 세트(memguard + train-watcher)를 한 번에 띄우고
#                 위조 불가한 발사 증거(launch-state-{name}.json)를 남긴다. (2026-08-25 신설, v3)
#
# 왜 필요한가 (Codex·Grok 교차감사 합의 결함): 종전 HARD GATE는 "발사 완료" 보고에
# TRAIN_PID·와쳐 PID를 적으라고 했지만 그 값은 채팅 문자열이라 살아있는 무관 PID나
# `kill -0 $$`로도 통과했고, 표준 시퀀스에 WATCHER_PID 캡처 줄조차 없었다.
#
# 증거 구조 (v3 — 2라운드 5자 검수 반영):
#  - 커널 증거: 학습 PID의 /proc/PID/cgroup 에 memguard가 만든 scope
#    (`memguard-{name}-<pid>.scope`, memguard-run.sh:106-108 `--unit`)가 있어야 PASS.
#    무관 PID의 argv를 베껴 state를 손으로 써도 그 PID는 이 scope 안에 없다.
#  - PID 재사용 차단: /proc/sys/kernel/random/boot_id + /proc/PID/stat 의 starttime(22번째 필드)을
#    기록·대조한다(같은 argv로 재사용된 PID도 starttime이 다르다).
#  - 시크릿 보호: state 는 umask 077(0600)로 만들고 argv는 `token=|key=|password=|secret=`류 값을
#    마스킹해 저장하며, 동일성 대조는 원문 argv의 sha256 으로 한다.
#  - exec 체인 안정화 후 캡처: memguard-run.sh:97/107 이 `exec`이므로 cmdline 에서
#    memguard-run.sh·systemd-run 이 사라질 때까지(최대 30s) 기다린 뒤 기록.
#  - --settle-sec(기본 10) 동안 1초 간격 생존 폴링(고정 sleep 3 한 번의 레이스 제거).
#  - 파일명은 --name 귀속, 기존 state 는 --force 없이 거부, 심볼릭 링크 거부.
#  - 와쳐 조기 종료 시에도 학습 쪽 provisional state 를 남기고 `reattach` 로 와쳐만 재부착.
#
# 사용 (학습 본 실행은 사용자 직접 — 이 스크립트도 사용자가 실행한다):
#   bash ~/.claude/tools/train-watcher/launch-set.sh launch \
#     --name {슬러그} --log train.log --done-regex '{완료 마커}' \
#     --eval-cmd '{eval 명령}' --title '{제목}' --expect 'train\.py' \
#     [--watcher-log <경로>] [--state <경로>] [--settle-sec 10] \
#       --state·--watcher-log 기본값(2026-10-06): <프로젝트 뿌리>/.scratch/launch/launch-state-{name}.json·watcher-{name}.log (state 옆에 .json.lock 도 생김).
#       뿌리는 `git rev-parse --show-toplevel`, git 저장소가 아니면 현재 폴더. 폴더가 없으면 만든다. 프로젝트 최상위에는 파일을 만들지 않는다.
#     [--memguard-args "--high 40G --max 56G"] [--watcher-args "--timeout-h 72"] [--force] \
#     [--intent intent/YYYY-MM-DD-slug.md]   # 의뢰서 경로(skills/intent). 없으면 경고만 — 진행 중 세션을 깨지 않기 위해 차단하지 않는다(2026-09-06)
#     [--design-review intent/YYYY-MM-DD-slug.review.md]   # 심사 시각 점검 보고서(rules-lazy/design-review-check.md, 2026-10-12). 안 주면 --intent 경로에서 .md 를 떼고 .review.md 를 붙인 파일을 찾는다.
#       있으면 state 에 design_review·design_review_sha256 을 적고, 없으면 표준에러 경고만 한다(차단 안 함). 새 설계에만 해당하며 재개·시드 추가·같은 설정 재발사는 면제. verify 는 보이되 PASS/FAIL 에 넣지 않는다.
#     [--done-log '<완료 마커가 찍히는 파일 글롭, 예: ckpt/exp/train_run_*/train.log>']
#     [--gpu N[,M]] [--vram-gb 30] [--cpu-cores 6] [--preflight-args '--util-max 70 --sample-sec 60']
#       GPU·CPU 사전검사(gpu_preflight.py, 2026-09-29). --gpu 가 없으면 명령의 RUN_GPU=·CUDA_VISIBLE_DEVICES= 에서 찾는다.
#       판이 이미 도는 GPU 에 올리려면 --vram-gb·--cpu-cores 필수, 미달이면 exit 76 으로 발사 전에 거부.
#       --preflight-args 에는 --gpu·--vram-gb·--cpu-cores 를 줄 수 없다(전용 인자가 정본 — 덮어쓰기 차단, 2026-10-01).
#     [--queue <대기 목록.json> --queue-item <판 id>]   # 대기 목록 자동 발사(2026-10-01, launch_queue.py 가 부른다). 둘은 함께 주고 --gpu <정수 한 장> 필수.
#       와쳐에 --on-exit(`launch_queue.py next …`)를 붙여 이 판이 끝나면 목록의 다음 판을 올리게 한다. state 에 queue·queue_item·queue_gpu 를 적는다.
#       사용자가 --watcher-args 로 --on-exit 를 직접 주는 것은 거부(승인 밖 명령이 실행되는 길).
#     [--queue-attempt K]   # 시도 번호 결박(선택, 2026-10-01). on-exit 의 `next` 가 --attempt K 로 보고해 이전 시도의 늦은 콜백이 현재 판을 닫지 못하게 한다. 없으면 옛 동작.
#     -- {학습 명령...}
#   ★tmux 창(tty)에서 부르면 학습 표준출력은 그 창으로, 표준에러만 --log 파일로 간다(2026-09-29 사용자 결정).
#    표준출력으로 찍히는 완료 마커는 --log 에 없으므로 --done-log 로 프로젝트 자체 로그 파일을 가리킨다.
#    tty 가 아니면(Bash 도구 등) 종전처럼 표준출력·에러 모두 --log 로 간다.
#   bash ~/.claude/tools/train-watcher/launch-set.sh reattach <state 경로> --confirm-eval '{eval 명령 원문}'   # 와쳐만 재부착 (state 의 eval_cmd 는 실행 sink 라 재입력 일치 필수)
#   bash ~/.claude/tools/train-watcher/launch-set.sh verify   <state 경로>
#
# 종료 코드: launch 0=두 프로세스 기동+검증 통과 / 1=기동은 됐으나 최종 verify FAIL
#            / 65=시작 후 검사 실패(조기 종료·scope 부재·memory.max/high 미설정·expect 토큰 불일치 — 뒤 세 가지는 status=rejected state 를 남김)
#            / 70=state 기록 실패 / 76=GPU·CPU 사전검사 거부(발사 안 함)
#            / 66=와쳐 조기 종료(학습 provisional state 는 남김 → reattach) / 67=state 기존 파일(--force 없음) 또는 같은 state 에 다른 launch·reattach 가 진행 중
#            / 64=인자·경로 오류(시크릿 형태 값·보호 옵션 재지정 포함).  verify 0=PASS / 1=FAIL.
# --expect 의미 (4라운드 검수): 학습 argv 의 **한 토큰 전체**(경로 접두 제외)와 일치하는 ERE. 결합 문자열 부분 일치가 아니다.
# 증거의 정본: 사용자 터미널의 launch 출력 원문. verify 는 state 의 사후 재확인이라 손으로 쓴 state 를 판별하지 못한다.
#
# 설계 제약: 학습 프로세스는 절대 죽이지 않는다. pipefail·ps|grep·pkill -f 사용 금지
#            (train-watcher.sh 헤더의 실사고 3건과 동일 이유). PID 판정은 /proc/PID 직접 읽기.
set -u
umask 077
# REF: knowledge/harness/code-history/tools__train-watcher__launch-set.sh.md

TW="$HOME/.claude/tools/train-watcher/train-watcher.sh"
MG="$HOME/.claude/tools/mem-guard/memguard-run.sh"

usage() { sed -n '2,49p' "$0" >&2; exit 64; }
proc_cmdline() { { tr '\0' ' ' < "/proc/$1/cmdline"; } 2>/dev/null; }
argv_token_match() {
    # WHY: 결합 문자열 부분 일치는 `env FAKE=train.py sleep 999999` 로 통과됐다(4라운드 검수). 그래서 한 토큰 전체와 맞춘다.
    tr '\0' '\n' < "/proc/$1/cmdline" 2>/dev/null | grep -qE -- "^(.*/)?($2)$"
}
has_secret_shape() { [ "$(mask "$1")" != "$1" ]; }
proc_scope() { grep -o 'memguard-[^/]*\.scope' "/proc/$1/cgroup" 2>/dev/null | head -1; }
proc_cgpath() { sed -n 's/^0::\(.*\)$/\1/p' "/proc/$1/cgroup" 2>/dev/null | head -1; }
cg_limit() { cat "/sys/fs/cgroup$1/$2" 2>/dev/null; }
watcher_pid_arg() {
    tr '\0' '\n' < "/proc/$1/cmdline" 2>/dev/null | awk 'p{print; p=0; next} $0=="--pid"{p=1; next} /^--pid=/{sub(/^--pid=/,""); print}'
}
proc_start() { awk '{print $22}' "/proc/$1/stat" 2>/dev/null; }
boot_id() { cat /proc/sys/kernel/random/boot_id 2>/dev/null; }
alive() { [ -d "/proc/$1" ] && [ -r "/proc/$1/cmdline" ]; }
sha() { printf '%s' "$1" | sha256sum | cut -c1-64; }
mask() {
    printf '%s' "$1" | sed -E \
        -e 's/((token|key|password|passwd|secret|api[_-]?key)=)[^ ]+/\1***/Ig' \
        -e 's/(--?[A-Za-z_-]*(key|token|password|passwd|secret)[A-Za-z_-]*)[[:space:]]+[^[:space:]]+/\1 ***/Ig' \
        -e 's/((Authorization|Cookie|X-Api-Key|Proxy-Authorization):[[:space:]]*)[^"'"'"']+/\1***/Ig' \
        -e 's/(Bearer|Basic)[[:space:]]+[^[:space:]"'"'"']+/\1 ***/Ig' \
        -e 's#(://[^/:[:space:]]+:)[^@[:space:]]+@#\1***@#g'
}
json_escape() { printf '%s' "$1" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'; }
refuse_symlink() { [ -L "$1" ] && { echo "FAIL: 심볼릭 링크 경로는 거부: $1" >&2; exit 64; }; return 0; }
read_field() { python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); v=d.get(sys.argv[2],""); print(v)' "$1" "$2"; }

lock_state() {
    # WHY: 잠금 없이는 같은 state 에 대한 두 명령이 state 를 서로 덮어쓰고 학습 · 와쳐가 둘 뜰 수 있었다(2026-10-01).
    # NEVER: 학습 · 와쳐 같은 오래 사는 자식에 잠금 fd 9 를 넘기지 않는다(`9>&-`). 넘기면 자식이 사는 동안 잠금이 안 풀린다.
    command -v flock >/dev/null 2>&1 || { echo "⚠️  flock 없음 — 같은 state 의 동시 발사·재부착 잠금을 건너뜁니다" >&2; return 0; }
    refuse_symlink "$1.lock"
    { exec 9>"$1.lock"; } 2>/dev/null || { echo "FAIL: 잠금 파일을 만들 수 없음: $1.lock" >&2; exit 64; }
    flock -n 9 || { echo "FAIL: 같은 state($1)에 대한 다른 launch·reattach 가 진행 중입니다 — 끝난 뒤 다시 실행하세요" >&2; exit 67; }
}

write_state() {
    local tmp="$1.tmp.$$"
    if ! { {
        printf '{\n'
        printf '  "schema": 3,\n'
        printf '  "nonce": %s,\n' "$(json_escape "$NONCE")"
        printf '  "name": %s,\n' "$(json_escape "$NAME")"
        printf '  "started_at": %s,\n' "$(json_escape "$STARTED")"
        printf '  "host": %s,\n' "$(json_escape "$(hostname)")"
        printf '  "boot_id": %s,\n' "$(json_escape "$(boot_id)")"
        printf '  "train_pid": %s,\n' "$TRAIN_PID"
        printf '  "train_start": %s,\n' "$(json_escape "$TRAIN_START")"
        printf '  "train_argv_masked": %s,\n' "$(json_escape "$(mask "$TRAIN_ARGV")")"
        printf '  "train_argv_sha256": %s,\n' "$(json_escape "$(sha "$TRAIN_ARGV")")"
        printf '  "train_scope": %s,\n' "$(json_escape "$TRAIN_SCOPE")"
        printf '  "expect": %s,\n' "$(json_escape "${EXPECT:-}")"
        printf '  "train_log": %s,\n' "$(json_escape "$(readlink -f "$LOG")")"
        printf '  "watcher_pid": %s,\n' "${WATCHER_PID:-0}"
        printf '  "watcher_start": %s,\n' "$(json_escape "${WATCHER_START:-}")"
        printf '  "watcher_argv_sha256": %s,\n' "$(json_escape "$(sha "${WATCHER_ARGV:-}")")"
        printf '  "watcher_log": %s,\n' "$(json_escape "$(readlink -f "$WLOG")")"
        printf '  "done_regex": %s,\n' "$(json_escape "$DONE_RX")"
        printf '  "done_log": %s,\n' "$(json_escape "${DONE_LOG:-}")"
        printf '  "eval_cmd": %s,\n' "$(json_escape "$EVAL_CMD")"
        printf '  "title": %s,\n' "$(json_escape "$TITLE")"
        printf '  "watcher_extra": %s,\n' "$(json_escape "$TW_ARGS")"
        printf '  "train_exe": %s,\n' "$(json_escape "${TRAIN_EXE:-}")"
        printf '  "train_cgroup": %s,\n' "$(json_escape "${TRAIN_CG:-}")"
        printf '  "mem_max": %s,\n' "$(json_escape "${MEM_MAX:-}")"
        printf '  "mem_high": %s,\n' "$(json_escape "${MEM_HIGH:-}")"
        printf '  "intent": %s,\n' "$(json_escape "${INTENT:-}")"
        printf '  "intent_sha256": %s,\n' "$(json_escape "${INTENT_SHA:-}")"
        printf '  "design_review": %s,\n' "$(json_escape "${DESIGN_REVIEW:-}")"
        printf '  "design_review_sha256": %s,\n' "$(json_escape "${DESIGN_REVIEW_SHA:-}")"
        if [ -n "${QUEUE:-}" ]; then
            printf '  "queue": %s,\n' "$(json_escape "$QUEUE")"
            printf '  "queue_item": %s,\n' "$(json_escape "$QUEUE_ITEM")"
            printf '  "queue_gpu": %s,\n' "$(json_escape "$QUEUE_GPU")"
            printf '  "queue_attempt": %s,\n' "$(json_escape "${QUEUE_ATTEMPT:-}")"
        fi
        printf '  "status": %s\n' "$(json_escape "$STATUS")"
        printf '}\n'
    } > "$tmp" && mv -f "$tmp" "$1"; }; then   # NEVER: 기록 실패를 조용히 넘기지 않는다(5라운드 Codex: 실패해도 "기록했습니다" 보고)
        rm -f "$tmp" 2>/dev/null
        echo "FAIL: state 기록 실패 — $1 (디렉터리 권한·존재 확인). 학습 PID ${TRAIN_PID:-?} 는 계속 돌고 있음, 증거 없음" >&2
        exit 70
    fi
}

refuse_protected_tw_args() {
    # WHY: 뒤쪽 --pid 999 가 파서에서 우선되면 감시 대상이 바뀐다(3라운드 검수). reattach 도 같은 검사를 쓴다: state 의
    # watcher_extra 뒤에 붙은 --eval-cmd 가 --confirm-eval 로 승인한 값을 덮어썼다(2026-09-08 검수, train-watcher.sh 는 마지막 값이 이긴다).
    local src="${2:---watcher-args}"
    for tok in $1; do
        case "$tok" in --on-exit|--on-exit=*)
            echo "$src 에 --on-exit 를 줄 수 없음 — 대기 목록 승인 밖 명령이 와쳐 종료 때 실행되는 길이라 --queue/--queue-item 으로만 붙는다" >&2; exit 64 ;; esac
        case "$tok" in --pid|--log|--done-regex|--done-log|--eval-cmd|--title|--eval-log|--report|--pid=*|--log=*|--done-regex=*|--done-log=*|--eval-cmd=*|--title=*|--eval-log=*|--report=*)
            echo "$src 에 보호 옵션($tok) 재지정 불가 — 전용 인자를 쓰라" >&2; exit 64 ;; esac
    done
}

queue_on_exit() {
    printf '/usr/bin/python3 %q next --queue %q --item %q --gpu %q' "$(dirname "$TW")/launch_queue.py" "$1" "$2" "$3"
    if [ -n "${4:-}" ]; then printf ' --attempt %q' "$4"; fi
    # shellcheck disable=SC2016
    printf ' --exit "$WATCH_EXIT"'
}

start_watcher() {
    # NEVER: 같은 nonce 의 재부착에서 와쳐 로그를 `>` 로 비우지 않는다. 이전 와쳐의 종료 · 실패 기록이 사라진다.
    if head -1 "$WLOG" 2>/dev/null | grep -qF "nonce=$NONCE"; then
        printf '[launch-set] reattach nonce=%s train_pid=%s at=%s\n' "$NONCE" "$TRAIN_PID" "$(date -Is)" >> "$WLOG"
    else
        printf '[launch-set] nonce=%s train_pid=%s started=%s\n' "$NONCE" "$TRAIN_PID" "$STARTED" > "$WLOG"
    fi
    local dl=() oe=()
    [ -n "${DONE_LOG:-}" ] && dl=(--done-log "$DONE_LOG")
    # NEVER: on-exit 를 TW_ARGS 에 섞지 않는다. TW_ARGS 는 단어 분리로 전개돼 공백 · 따옴표가 든 on-exit 이 깨진다.
    [ -n "${ON_EXIT:-}" ] && oe=(--on-exit "$ON_EXIT")
    # shellcheck disable=SC2086
    nohup bash "$TW" --pid "$TRAIN_PID" --log "$LOG" --done-regex "$DONE_RX" \
        --eval-cmd "$EVAL_CMD" --title "$TITLE" ${dl[@]+"${dl[@]}"} ${oe[@]+"${oe[@]}"} $TW_ARGS >> "$WLOG" 2>&1 9>&- &
    WATCHER_PID=$!
    local i=0
    while [ $i -lt 5 ]; do
        alive "$WATCHER_PID" || return 1
        sleep 1; i=$((i+1))
    done
    WATCHER_ARGV="$(proc_cmdline "$WATCHER_PID")"
    WATCHER_START="$(proc_start "$WATCHER_PID")"
    return 0
}

refuse_fake_preflight() {
    [ -z "${GPU_PREFLIGHT_FAKE:-}" ] || { echo "FAIL: GPU_PREFLIGHT_FAKE 가 설정돼 있음 — 시험 전용 변수라 실제 발사·재부착에서는 거부합니다(unset 후 다시 실행)" >&2; exit 64; }
}

cmd_launch() {
    refuse_fake_preflight
    NAME=""; LOG=""; DONE_RX=""; EVAL_CMD=""; TITLE=""; WLOG=""; STATE=""; EXPECT=""; INTENT=""; INTENT_SHA=""
    MG_ARGS=""; TW_ARGS=""; SETTLE=10; FORCE=0; DONE_LOG=""; DESIGN_REVIEW=""; DESIGN_REVIEW_SHA=""
    GPU_SEL=""; VRAM_GB=""; CPU_CORES=""; PF_ARGS=""; QUEUE=""; QUEUE_ITEM=""; QUEUE_GPU=""; QUEUE_ATTEMPT=""; ON_EXIT=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --queue) QUEUE="$2"; shift 2 ;;
            --queue-item) QUEUE_ITEM="$2"; shift 2 ;;
            --queue-attempt) QUEUE_ATTEMPT="$2"; shift 2 ;;
            --gpu) GPU_SEL="$2"; shift 2 ;;
            --vram-gb) VRAM_GB="$2"; shift 2 ;;
            --cpu-cores) CPU_CORES="$2"; shift 2 ;;
            --preflight-args) PF_ARGS="$2"; shift 2 ;;
            --expect) EXPECT="$2"; shift 2 ;;
            --name) NAME="$2"; shift 2 ;;
            --log) LOG="$2"; shift 2 ;;
            --done-regex) DONE_RX="$2"; shift 2 ;;
            --eval-cmd) EVAL_CMD="$2"; shift 2 ;;
            --title) TITLE="$2"; shift 2 ;;
            --watcher-log) WLOG="$2"; shift 2 ;;
            --state) STATE="$2"; shift 2 ;;
            --settle-sec) SETTLE="$2"; shift 2 ;;
            --memguard-args) MG_ARGS="$2"; shift 2 ;;
            --watcher-args) TW_ARGS="$2"; shift 2 ;;
            --intent) INTENT="$2"; shift 2 ;;
            --design-review) DESIGN_REVIEW="$2"; shift 2 ;;
            --done-log) DONE_LOG="$2"; shift 2 ;;
            --force) FORCE=1; shift ;;
            --) shift; break ;;
            *) echo "알 수 없는 인자: $1" >&2; usage ;;
        esac
    done
    [ $# -gt 0 ] || { echo "-- 뒤에 학습 명령이 없습니다" >&2; usage; }
    for v in NAME LOG DONE_RX EVAL_CMD TITLE EXPECT; do
        [ -n "${!v}" ] || { echo "--$(echo "$v" | tr 'A-Z_' 'a-z-') 필수 (--expect 는 학습 argv 의 한 토큰 전체와 일치해야 할 ERE — 경로 접두 허용, 예: 'train\.py' 또는 'torchrun')" >&2; usage; }
    done
    case "$NAME" in *[!A-Za-z0-9._-]*) echo "--name 은 [A-Za-z0-9._-]만: $NAME" >&2; exit 64 ;; esac
    case "$SETTLE" in ''|*[!0-9]*) echo "--settle-sec 는 정수: $SETTLE" >&2; exit 64 ;; esac
    # WHY: eval_cmd · title · done_regex · watcher_extra 는 state 에 평문 저장 · 와쳐 argv 로 노출된다(4라운드 검수).
    for v in EVAL_CMD TITLE DONE_RX TW_ARGS; do
        if has_secret_shape "${!v}"; then
            echo "FAIL: --$(echo "$v" | tr 'A-Z_' 'a-z-') 값에 시크릿 형태(token=|key=|password=|--api-key VALUE …)가 있음 — state·와쳐 argv 에 평문으로 남으므로 거부. 자격증명은 환경 파일·헬퍼로 옮기라" >&2; exit 64
        fi
    done
    refuse_protected_tw_args "$TW_ARGS"
    # WHY: preflight-args 로 같은 키를 주면 정본을 덮어써 검사 대상 · 한도가 바뀐다(2026-10-01).
    for tok in $PF_ARGS; do
        case "$tok" in --gpu|--vram-gb|--cpu-cores|--gpu=*|--vram-gb=*|--cpu-cores=*)
            echo "--preflight-args 에 $tok 를 줄 수 없음 — 전용 인자(--gpu·--vram-gb·--cpu-cores)를 쓰라" >&2; exit 64 ;; esac
    done
    if [ -n "$QUEUE_ATTEMPT" ]; then case "$QUEUE_ATTEMPT" in *[!0-9]*) echo "--queue-attempt 는 정수: $QUEUE_ATTEMPT" >&2; exit 64 ;; esac; fi
    if [ -n "$QUEUE$QUEUE_ITEM" ]; then
        [ -n "$QUEUE" ] && [ -n "$QUEUE_ITEM" ] || { echo "--queue 와 --queue-item 은 함께 줘야 합니다" >&2; exit 64; }
        [ -f "$QUEUE" ] && [ ! -L "$QUEUE" ] || { echo "--queue 파일이 없거나 링크임: $QUEUE" >&2; exit 64; }
        case "$GPU_SEL" in ''|*[!0-9]*) echo "--queue 는 --gpu <정수 한 장> 이 필요합니다(다음 판이 이 GPU 에 올라갑니다): '${GPU_SEL}'" >&2; exit 64 ;; esac
        QUEUE="$(readlink -f "$QUEUE")"; QUEUE_GPU="$GPU_SEL"
        ON_EXIT="$(queue_on_exit "$QUEUE" "$QUEUE_ITEM" "$QUEUE_GPU" "$QUEUE_ATTEMPT")"
    fi
    if [ -z "$WLOG" ] || [ -z "$STATE" ]; then
        LROOT="$(git -C "$PWD" rev-parse --show-toplevel 2>/dev/null)" || LROOT="$PWD"
        [ -n "$LROOT" ] || LROOT="$PWD"
        LDIR="$LROOT/.scratch/launch"
        mkdir -p "$LDIR" 2>/dev/null || { echo "기본 출력 폴더를 만들 수 없음: $LDIR (발사 전 거부 — --state·--watcher-log 를 직접 주세요)" >&2; exit 64; }
        [ -n "$WLOG" ] || WLOG="$LDIR/watcher-${NAME}.log"
        [ -n "$STATE" ] || STATE="$LDIR/launch-state-${NAME}.json"
    fi
    # WHY: --intent 가 없으면 경고만 한다(2026-09-06 사용자 결정: 발사는 경고, 하네스 feat 커밋은 차단).
    if [ -n "$INTENT" ]; then
        [ -f "$INTENT" ] && [ ! -L "$INTENT" ] || { echo "--intent 파일이 없거나 링크임: $INTENT" >&2; exit 64; }
        INTENT_SHA="$(sha "$(cat "$INTENT")")"
    else
        echo "⚠️  --intent 없음 — 의뢰서(intent.md) 경로가 없는 발사. 착수 전 intent.md 를 커밋하고 --intent 로 가리키는 것이 기본형이다(skills/intent). 발사는 계속한다."
    fi
    # WHY: 심사 시각 점검 보고서(rules-lazy/design-review-check.md)가 없으면 경고만 한다(2026-10-12 사용자 결정: 차단 아님).
    DR_PATH="$DESIGN_REVIEW"; DESIGN_REVIEW=""
    if [ -z "$DR_PATH" ] && [ -n "$INTENT" ]; then DR_PATH="${INTENT%.md}.review.md"; fi
    if [ -n "$DR_PATH" ]; then
        if [ -e "$DR_PATH" ] || [ -L "$DR_PATH" ]; then
            [ -f "$DR_PATH" ] && [ ! -L "$DR_PATH" ] || { echo "심사 시각 점검 보고서가 일반 파일이 아니거나 링크임: $DR_PATH" >&2; exit 64; }
            DESIGN_REVIEW="$DR_PATH"; DESIGN_REVIEW_SHA="$(sha "$(cat "$DR_PATH")")"
        else
            echo "경고: 심사 시각 점검 보고서 없음($DR_PATH) — 새 설계라면 rules-lazy/design-review-check.md 절차를 거칠 것. 재개·시드 추가·같은 설정 재발사는 면제" >&2
        fi
    fi
    # WHY: 부모 없는 --state 면 프로세스만 남고 기록이 실패했다(5라운드 Codex). 그래서 발사 전에 확인한다.
    STATE_DIR="$(dirname "$STATE")"
    [ -d "$STATE_DIR" ] && [ -w "$STATE_DIR" ] || { echo "--state 디렉터리가 없거나 쓸 수 없음: $STATE_DIR (발사 전 거부)" >&2; exit 64; }
    if ! { ( : > "$STATE.probe.$$" ) 2>/dev/null && rm -f "$STATE.probe.$$"; }; then echo "--state 경로에 파일을 만들 수 없음: $STATE (발사 전 거부)" >&2; exit 64; fi
    [ -r "$TW" ] || { echo "train-watcher.sh 없음: $TW" >&2; exit 64; }
    [ -r "$MG" ] || { echo "memguard-run.sh 없음: $MG" >&2; exit 64; }
    refuse_symlink "$LOG"; refuse_symlink "$WLOG"; refuse_symlink "$STATE"
    lock_state "$STATE"
    if [ -e "$STATE" ] && [ "$FORCE" != 1 ]; then
        echo "FAIL: state 파일이 이미 있습니다($STATE) — 같은 이름의 발사가 진행 중이거나 남은 증거입니다. 확인 후 --force 또는 다른 --name" >&2
        exit 67
    fi

    # WHY: GPU 번호를 모르면 경고만 하고 넘어간다(GPU 를 지정하지 않는 옛 명령 호환, 2026-09-29 사용자 결정의 사전검사).
    if [ -z "$GPU_SEL" ]; then
        for tok in "$@"; do
            case "$tok" in RUN_GPU=*|CUDA_VISIBLE_DEVICES=*) GPU_SEL="${tok#*=}"; break ;; esac
        done
        [ -n "$GPU_SEL" ] || GPU_SEL="${CUDA_VISIBLE_DEVICES:-}"
    fi
    if [ -n "$GPU_SEL" ]; then
        # WHY: 정본(--gpu · --vram-gb · --cpu-cores)을 맨 뒤에 둔다. argparse 는 같은 옵션이 여러 번이면 마지막 값이 이겨
        # 약어(--vram 등)로 키 거부를 피해도 정본이 덮는다(2026-10-01).
        PF=(python3 "$(dirname "$TW")/gpu_preflight.py")
        # shellcheck disable=SC2206
        [ -n "$PF_ARGS" ] && PF+=($PF_ARGS)
        PF+=(--gpu "$GPU_SEL")
        [ -n "$VRAM_GB" ] && PF+=(--vram-gb "$VRAM_GB")
        [ -n "$CPU_CORES" ] && PF+=(--cpu-cores "$CPU_CORES")
        "${PF[@]}"; PF_RC=$?
        if [ "$PF_RC" -ne 0 ]; then
            echo "FAIL: GPU·CPU 사전검사 거부(rc=$PF_RC) — 발사하지 않았습니다. 빈 GPU 를 고르거나, 여러 판 올리기면 --vram-gb·--cpu-cores 를 주세요" >&2
            exit 76
        fi
    else
        echo "⚠️  GPU 번호를 알 수 없어 GPU·CPU 사전검사를 건너뜁니다(--gpu N 을 주면 검사합니다). 발사는 계속합니다." >&2
    fi

    NONCE="$(date +%Y%m%dT%H%M%S)-$$-$RANDOM"
    STARTED="$(date -Is)"

    # WHY: 창(tty)에서는 표준출력을 창으로 보낸다. 표준출력까지 로그로 받던 판은 40분에 14.4MB · 9.7만 줄이었다(실측).
    TRAIN_TTY=""
    if [ -t 0 ] && [ -t 1 ]; then TRAIN_TTY="$(tty)"; fi
    if [ -n "$TRAIN_TTY" ] && [ -z "$DONE_LOG" ]; then
        echo "⚠️  학습 표준출력은 이 창으로 가고 --log 에는 표준에러만 남습니다. 완료 마커('$DONE_RX')가 표준출력으로 찍히는 프로젝트면 --done-log 로 프로젝트 로그 파일을 지정하세요. 발사는 계속합니다."
    fi

    # NEVER: 서브셸과 tools/mem-guard/memguard-run.sh 의 exec 를 빼지 않는다. $! 가 그대로 학습 프로세스 PID 여야 한다.
    # NEVER: nohup 을 쓰지 않는다. tty 인 표준입출력을 강제로 바꾸므로 HUP · TTIN · TTOU 무시를 직접 건다.
    # NEVER: COLUMNS · LINES 를 남기지 않는다. 환경에 있으면 Rich 가 tty 크기 대신 그 값을 쓴다.
    if [ -n "$TRAIN_TTY" ]; then
        # shellcheck disable=SC2086,SC2094
        ( trap '' HUP TTIN TTOU; unset COLUMNS LINES; exec bash "$MG" --name "$NAME" $MG_ARGS -- "$@" ) < "$TRAIN_TTY" > "$TRAIN_TTY" 2> "$LOG" 9>&- &
    else
        # shellcheck disable=SC2086
        ( trap '' HUP TTIN TTOU; unset COLUMNS LINES; exec bash "$MG" --name "$NAME" $MG_ARGS -- "$@" ) < /dev/null > "$LOG" 2>&1 9>&- &
    fi
    TRAIN_PID=$!

    i=0
    while [ $i -lt 30 ]; do
        alive "$TRAIN_PID" || break
        cl="$(proc_cmdline "$TRAIN_PID")"
        # WHY: launch-set.sh 는 exec 전 서브셸이 부모 argv 를 가진 채 잠깐 존재하는 경우다(2026-09-29 서브셸 발사로 추가).
        case "$cl" in *memguard-run.sh*|*systemd-run*|*launch-set.sh*) sleep 1; i=$((i+1)) ;; *) break ;; esac
    done
    i=0
    while [ $i -lt "$SETTLE" ]; do
        if ! alive "$TRAIN_PID"; then
            echo "FAIL: 학습 프로세스가 ${i}s 안에 종료됨 (memguard preflight 거부 exit 75/77 또는 크래시) — $LOG 확인" >&2
            tail -5 "$LOG" >&2 2>/dev/null
            exit 65
        fi
        sleep 1; i=$((i+1))
    done
    TRAIN_ARGV="$(proc_cmdline "$TRAIN_PID")"
    TRAIN_START="$(proc_start "$TRAIN_PID")"
    TRAIN_SCOPE="$(proc_scope "$TRAIN_PID")"
    TRAIN_EXE="$(readlink -f "/proc/$TRAIN_PID/exe" 2>/dev/null)"
    TRAIN_CG="$(proc_cgpath "$TRAIN_PID")"
    MEM_MAX="$(cg_limit "$TRAIN_CG" memory.max)"; MEM_HIGH="$(cg_limit "$TRAIN_CG" memory.high)"
    # WHY: scope 이름만으로는 무제한 scope 도 인정됐다(3라운드 검수). 실패하면 state · 와쳐 없이 프로세스만 남던 경로가 있었다(4라운드 Codex).
    reject_after_start() {
        STATUS="rejected: $1"; WATCHER_PID=0; WATCHER_START=""; WATCHER_ARGV=""
        refuse_symlink "$STATE"; write_state "$STATE"
        echo "FAIL: $1" >&2
        echo "      학습(PID $TRAIN_PID)은 계속 돕니다(죽이지 않음). 사유·PID·starttime 을 $STATE 에 status=rejected 로 기록했습니다." >&2
        echo "      조치: 학습이 정상이면 사용자가 직접 확인 후 수동 와쳐 부착(rules-lazy/background-task.md 수동 시퀀스), 아니면 사용자가 직접 종료." >&2
        exit 65
    }
    if [ -z "$MEM_MAX" ] || [ "$MEM_MAX" = "max" ]; then
        reject_after_start "학습 cgroup($TRAIN_CG)의 memory.max 가 '${MEM_MAX:-없음}' — memguard 한도가 걸리지 않음"
    fi
    if [ -z "$MEM_HIGH" ] || [ "$MEM_HIGH" = "max" ]; then   # WHY: memguard 는 MemoryHigh 도 항상 건다(기본 40G)
        reject_after_start "학습 cgroup($TRAIN_CG)의 memory.high 가 '${MEM_HIGH:-없음}' — memguard 스로틀 한도가 걸리지 않음"
    fi
    if ! argv_token_match "$TRAIN_PID" "$EXPECT"; then
        reject_after_start "학습 argv 의 어느 토큰도 --expect '$EXPECT' 와 통째로 일치하지 않음 (실제: $(mask "$TRAIN_ARGV")) — 학습 명령이 아니거나 패턴 오류"
    fi
    # WHY: `bash -c 'exec -a train.py sleep …'` 는 argv[0] 만 위조해 토큰 검사를 통과한다. exe 는 위조하지 못한다(7라운드 렌즈2).
    case "$(basename "${TRAIN_EXE:-}")" in
        python*|torchrun|accelerate|deepspeed|ray|uv|java|julia|Rscript|bash|sh|dash|zsh) : ;;
        *) reject_after_start "학습 exe(${TRAIN_EXE:-없음})가 허용 런타임(python*/torchrun/accelerate/deepspeed/ray/uv/java/julia/Rscript/셸)이 아님 — argv[0] 위조 의심" ;;
    esac
    case "$TRAIN_SCOPE" in
        memguard-"$NAME"-*) : ;;
        *) reject_after_start "학습 PID $TRAIN_PID 가 memguard scope(memguard-$NAME-*.scope) 안에 없음 — --allow-unenforced 로 돌았거나 래핑이 빠짐 (cgroup: ${TRAIN_SCOPE:-없음})" ;;
    esac
    STATUS="provisional-no-watcher"; WATCHER_PID=0; WATCHER_ARGV=""; WATCHER_START=""
    write_state "$STATE"

    if ! start_watcher; then
        echo "FAIL: 와쳐 조기 종료 — $WLOG 확인. 학습은 계속 돌고 있고 provisional state 가 $STATE 에 있음 → 원인 해결 후:" >&2
        echo "      bash $0 reattach $STATE" >&2
        tail -5 "$WLOG" >&2 2>/dev/null; exit 66
    fi
    STATUS="launched"
    write_state "$STATE"
    exec 9>&-
    echo "LAUNCHED nonce=$NONCE train_pid=$TRAIN_PID watcher_pid=$WATCHER_PID scope=$TRAIN_SCOPE state=$STATE"
    # NEVER: cmd_verify 를 서브셸 밖에서 부르지 않는다. 끝에서 exit 해 launch 가 그 자리에서 끝난다.
    ( cmd_verify "$STATE" ); VRC=$?

    # NEVER: 이 tail 을 `> >(tee "$LOG")` 로 바꾸지 않는다. tee 가 HUP 무시 보호 밖이고 PID · exec 체인 불변식 바로 옆을 건드린다.
    # NEVER: tail 에 nohup 을 붙이지 않는다. tmux 의 실제 tty 에서 nohup 이 출력을 ./nohup.out 으로 돌렸다(2026-09-28 재발 실사고).
    # WHY: -s 0.05 는 inotify 가 바닥난 서버(실측)에서 tail 이 폴링이라 기본 1초 간격이면 몰린 줄이 한꺼번에 나오기 때문이다.
    if alive "$TRAIN_PID"; then
        tail -n +1 -f -s 0.05 --pid="$TRAIN_PID" "$LOG" 2>/dev/null &
    else
        echo "── 학습 프로세스가 이미 종료됨 — $LOG 마지막 20줄 ──"
        tail -n 20 "$LOG" 2>/dev/null
    fi
    exit "$VRC"
}

cmd_reattach() {
    refuse_fake_preflight
    STATE="${1:-}"; [ -n "$STATE" ] && [ -r "$STATE" ] || { echo "FAIL: state 파일 없음"; exit 64; }
    refuse_symlink "$STATE"
    lock_state "$STATE"
    NONCE="$(read_field "$STATE" nonce)"; NAME="$(read_field "$STATE" name)"; STARTED="$(read_field "$STATE" started_at)"
    TRAIN_PID="$(read_field "$STATE" train_pid)"; TRAIN_START="$(read_field "$STATE" train_start)"
    TRAIN_SCOPE="$(read_field "$STATE" train_scope)"; LOG="$(read_field "$STATE" train_log)"; WLOG="$(read_field "$STATE" watcher_log)"
    TRAIN_ARGV="$(proc_cmdline "$TRAIN_PID")"; EXPECT="$(read_field "$STATE" expect)"; TRAIN_EXE="$(read_field "$STATE" train_exe)"
    TRAIN_CG="$(read_field "$STATE" train_cgroup)"; MEM_MAX="$(read_field "$STATE" mem_max)"; MEM_HIGH="$(read_field "$STATE" mem_high)"
    DESIGN_REVIEW="$(read_field "$STATE" design_review)"; DESIGN_REVIEW_SHA="$(read_field "$STATE" design_review_sha256)"
    # WHY: 원 발사 provenance 를 확인한 뒤에만 재부착해 재부팅 · 무관 PID 세탁을 막는다(3라운드 검수).
    case "$(read_field "$STATE" status)" in rejected*) echo "FAIL: 이 state 는 발사 시 검사에 실패한 기록(status=rejected)이라 재부착 대상이 아님 — 사유를 해결하고 새로 발사하거나 사용자가 수동 부착"; exit 65 ;; esac
    [ "$(hostname)" = "$(read_field "$STATE" host)" ] || { echo "FAIL: host 불일치 — 다른 기기의 state"; exit 65; }
    [ "$(boot_id)" = "$(read_field "$STATE" boot_id)" ] || { echo "FAIL: boot_id 불일치 — 재부팅 후 PID는 재부착 대상이 아님"; exit 65; }
    [ "$(proc_scope "$TRAIN_PID")" = "$TRAIN_SCOPE" ] || { echo "FAIL: memguard scope 불일치"; exit 65; }
    [ "$(proc_cgpath "$TRAIN_PID")" = "$TRAIN_CG" ] || { echo "FAIL: cgroup 경로 불일치"; exit 65; }
    DONE_RX="$(read_field "$STATE" done_regex)"; EVAL_CMD="$(read_field "$STATE" eval_cmd)"
    DONE_LOG="$(read_field "$STATE" done_log)"
    TITLE="$(read_field "$STATE" title)"; TW_ARGS="$(read_field "$STATE" watcher_extra)"
    refuse_protected_tw_args "$TW_ARGS" "state 의 watcher_extra"
    QUEUE="$(read_field "$STATE" queue)"; QUEUE_ITEM="$(read_field "$STATE" queue_item)"; QUEUE_GPU="$(read_field "$STATE" queue_gpu)"
    QUEUE_ATTEMPT="$(read_field "$STATE" queue_attempt)"
    ON_EXIT=""; [ -z "$QUEUE" ] || ON_EXIT="$(queue_on_exit "$QUEUE" "$QUEUE_ITEM" "$QUEUE_GPU" "$QUEUE_ATTEMPT")"
    # WHY: state 의 eval_cmd 는 실행 sink 다. 손으로 쓴 state 로 reattach 하면 학습 종료 후 임의 명령이 실행된다(5라운드 Codex).
    CONFIRM=""; shift; while [ $# -gt 0 ]; do case "$1" in --confirm-eval) CONFIRM="$2"; shift 2 ;; *) echo "reattach 인자 오류: $1" >&2; exit 64 ;; esac; done
    if [ -z "$CONFIRM" ] || [ "$CONFIRM" != "$EVAL_CMD" ]; then
        echo "FAIL: reattach 는 --confirm-eval '<eval 명령 원문>' 이 state 의 eval_cmd 와 정확히 일치해야 함 (state 는 실행 sink 라 재입력으로 승인). state 값(masked): $(mask "$EVAL_CMD")" >&2; exit 65
    fi
    # WHY: 기본 state 위치가 <뿌리>/.scratch/launch/ 라 학습 로그(--log)가 state 디렉터리 밖이 된다(2026-10-06). 그래서 state 가 정확히
    # `*/.scratch/launch` 에 있으면 허용 범위를 그 뿌리 하위로 넓힌다. 그 밖의 위치는 state 디렉터리 하위만이다.
    SDIR="$(cd "$(dirname "$STATE")" && pwd -P)"
    SBASE="$SDIR"; case "$SDIR" in */.scratch/launch) SBASE="${SDIR%/.scratch/launch}" ;; esac
    # NEVER: 넓힌 범위(SBASE)를 와쳐가 쓰는 WLOG 에 적용하지 않는다. 변조된 state 로 프로젝트 안 임의 파일을 덮어쓰게 된다(2026-10-06 main 검토).
    for p in "$LOG" "$WLOG"; do
        refuse_symlink "$p"
        if [ "$p" = "$LOG" ]; then ALLOW_BASE="$SBASE"; else ALLOW_BASE="$SDIR"; fi
        case "$(readlink -f "$p")" in "$SDIR"/*|"$ALLOW_BASE"/*) : ;; *) echo "FAIL: state 에 적힌 경로가 state 디렉터리 밖: $p"; exit 64 ;; esac
    done
    alive "$TRAIN_PID" || { echo "FAIL: 학습 PID $TRAIN_PID 가 살아있지 않음 — 재부착 대상 없음"; exit 65; }
    [ "$(proc_start "$TRAIN_PID")" = "$TRAIN_START" ] || { echo "FAIL: PID $TRAIN_PID 의 starttime 이 기록과 다름(재사용된 PID)"; exit 65; }
    [ "$(readlink -f "/proc/$TRAIN_PID/exe" 2>/dev/null)" = "$TRAIN_EXE" ] || { echo "FAIL: 학습 exe 불일치"; exit 65; }
    OLD_WP="$(read_field "$STATE" watcher_pid)"
    if [ "${OLD_WP:-0}" != 0 ] && alive "$OLD_WP"; then echo "기존 와쳐 PID $OLD_WP 가 아직 살아있음 — 재부착 불필요"; cmd_verify "$STATE"; fi
    if ! start_watcher; then echo "FAIL: 와쳐 재부착 실패 — $WLOG 확인" >&2; exit 66; fi
    STATUS="launched(reattached $(date -Is))"
    write_state "$STATE"
    echo "REATTACHED watcher_pid=$WATCHER_PID state=$STATE"
    cmd_verify "$STATE"
}

# shellcheck disable=SC2319
cmd_verify() {
    STATE="${1:-}"
    [ -n "$STATE" ] && [ -r "$STATE" ] || { echo "FAIL: state 파일 없음: ${STATE:-(미지정)}"; exit 1; }
    NONCE="$(read_field "$STATE" nonce)"; NAME="$(read_field "$STATE" name)"; TP="$(read_field "$STATE" train_pid)"; WP="$(read_field "$STATE" watcher_pid)"
    TSHA="$(read_field "$STATE" train_argv_sha256)"; TS="$(read_field "$STATE" train_scope)"; TST="$(read_field "$STATE" train_start)"
    WSHA="$(read_field "$STATE" watcher_argv_sha256)"; WST="$(read_field "$STATE" watcher_start)"
    WLOG="$(read_field "$STATE" watcher_log)"; HOST="$(read_field "$STATE" host)"; BID="$(read_field "$STATE" boot_id)"
    STATUS="$(read_field "$STATE" status)"; TAM="$(read_field "$STATE" train_argv_masked)"; EXP="$(read_field "$STATE" expect)"; TEXE="$(read_field "$STATE" train_exe)"
    TCG="$(read_field "$STATE" train_cgroup)"; TMAX="$(read_field "$STATE" mem_max)"; THIGH="$(read_field "$STATE" mem_high)"; SCHEMA="$(read_field "$STATE" schema)"
    INT="$(read_field "$STATE" intent)"; INTSHA="$(read_field "$STATE" intent_sha256)"
    ok=1
    chk() { if [ "$1" = 0 ]; then echo "  ✅ $2"; else echo "  ❌ $2"; ok=0; fi; }
    warn() { if [ "$1" = 0 ]; then echo "  ✅ $2"; else echo "  ⚠️  $2 (참고 항목 — 판정에 미포함)"; fi; }
    echo "VERIFY $STATE (name=$NAME status=$STATUS)"
    [ ! -L "$STATE" ]; chk $? "state 경로가 심볼릭 링크 아님"
    [ "$SCHEMA" = 3 ]; chk $? "state schema=3"
    case "$STATUS" in launched*) chk 0 "status=launched (provisional 아님)" ;; *) chk 1 "status=launched (현재: $STATUS — 와쳐 미부착이면 reattach)" ;; esac
    [ "$(stat -c %a "$STATE" 2>/dev/null)" = "600" ]; chk $? "state 파일 권한 0600"
    [ "$(hostname)" = "$HOST" ]; chk $? "host 일치 ($HOST)"
    [ "$(boot_id)" = "$BID" ]; chk $? "boot_id 일치 (재부팅 후 PID 아님)"
    alive "$TP"; chk $? "학습 PID $TP 생존"
    if alive "$TP"; then
        [ "$(proc_start "$TP")" = "$TST" ]; chk $? "학습 PID starttime 동일 (PID 재사용 아님)"
        [ "$(readlink -f "/proc/$TP/exe" 2>/dev/null)" = "$TEXE" ]; chk $? "학습 exe 동일 ($TEXE)"
        case "$(basename "$TEXE")" in python*|torchrun|accelerate|deepspeed|ray|uv|java|julia|Rscript|bash|sh|dash|zsh) chk 0 "학습 exe 가 허용 런타임 ($(basename "$TEXE"))" ;; *) chk 1 "학습 exe 가 허용 런타임 (현재: $(basename "$TEXE") — argv[0] 위조 의심)" ;; esac
        # WHY: argv 는 setproctitle 로 바뀔 수 있어(PyTorch · Lightning · ray) 참고 항목이다. 정체성은 starttime · exe · scope 가 판정한다(3라운드 검수).
        [ "$(sha "$(proc_cmdline "$TP")")" = "$TSHA" ]; warn $? "학습 argv sha256 동일"
        [ -n "$EXP" ] && argv_token_match "$TP" "$EXP"; warn $? "학습 argv 토큰이 expect 패턴('$EXP')과 통째로 일치 (발사 시점엔 하드 검사됨)"
        cur_scope="$(proc_scope "$TP")"
        case "$cur_scope" in memguard-"$NAME"-*) chk 0 "학습 PID가 memguard scope 안 ($cur_scope) — 래핑·발사 사실의 커널 증거" ;; *) chk 1 "학습 PID가 memguard-$NAME-*.scope 안 (현재: ${cur_scope:-없음})" ;; esac
        [ "$cur_scope" = "$TS" ]; chk $? "scope가 발사 시각 기록과 동일"
        [ "$(proc_cgpath "$TP")" = "$TCG" ]; chk $? "cgroup 경로 동일 ($TCG)"
        cur_max="$(cg_limit "$TCG" memory.max)"; cur_high="$(cg_limit "$TCG" memory.high)"
        [ -n "$cur_max" ] && [ "$cur_max" != "max" ] && [ "$cur_max" = "$TMAX" ]; chk $? "memory.max 한도 실효 ($cur_max, 기록 $TMAX)"
        [ "$cur_high" = "$THIGH" ]; chk $? "memory.high 동일 ($cur_high)"
    fi
    [ "${WP:-0}" != 0 ] && alive "$WP"; chk $? "와쳐 PID ${WP:-0} 생존"
    if [ "${WP:-0}" != 0 ] && alive "$WP"; then
        [ "$(proc_start "$WP")" = "$WST" ]; chk $? "와쳐 PID starttime 동일"
        cur="$(proc_cmdline "$WP")"
        [ "$(sha "$cur")" = "$WSHA" ]; chk $? "와쳐 argv sha256 동일"
        # WHY: 부분 일치로는 `/tmp/fake/train-watcher.sh` 더미가 통과했다(5라운드 렌즈2). 실경로와 정확히 맞춘다.
        TW_REAL="$(readlink -f "$TW")"
        tr '\0' '\n' < "/proc/$WP/cmdline" 2>/dev/null | grep -qxF -e "$TW" -e "$TW_REAL"; chk $? "와쳐 argv 의 스크립트 토큰이 정본 train-watcher.sh 실경로($TW_REAL)와 정확히 일치"
        [ "$(readlink -f "/proc/$WP/exe" 2>/dev/null)" = "$(readlink -f "$(command -v bash)")" ]; chk $? "와쳐 exe 가 bash"
        pids="$(watcher_pid_arg "$WP")"
        [ "$(printf '%s\n' "$pids" | grep -c .)" = 1 ] && [ "$pids" = "$TP" ]; chk $? "와쳐 --pid 가 정확히 1개이고 이 학습 PID($TP) (NUL 단위 argv 파싱)"
    fi
    head -1 "$WLOG" 2>/dev/null | grep -qF "nonce=$NONCE"; chk $? "와쳐 로그 첫 줄 nonce 일치 (옛 로그 아님)"
    echo "  train_argv(masked): $TAM"
    if [ -n "$INT" ]; then
        if [ -f "$INT" ] && [ "$(sha "$(cat "$INT")")" = "$INTSHA" ]; then warn 0 "intent $INT (sha256 일치)"; else warn 1 "intent $INT — 파일이 없거나 발사 뒤 바뀜(sha256 불일치)"; fi
    else
        warn 1 "intent 미기록 — 의뢰서 없는 발사 (skills/intent)"
    fi
    DR="$(read_field "$STATE" design_review)"; DRSHA="$(read_field "$STATE" design_review_sha256)"
    if [ -n "$DR" ]; then
        if [ -f "$DR" ] && [ "$(sha "$(cat "$DR")")" = "$DRSHA" ]; then warn 0 "design_review $DR (sha256 일치)"; else warn 1 "design_review $DR — 파일이 없거나 발사 뒤 바뀜(sha256 불일치)"; fi
    else
        warn 1 "design_review 미기록 — 심사 시각 점검 보고서 없음 (새 설계면 rules-lazy/design-review-check.md, 재개·시드 추가·같은 설정 재발사는 면제)"
    fi
    if [ "$ok" = 1 ]; then echo "VERIFY PASS nonce=$NONCE train_pid=$TP watcher_pid=$WP"; exit 0
    else echo "VERIFY FAIL — 위 ❌ 항목이 발사 증거 불충족 (완료 선언 금지)"; exit 1; fi
}

case "${1:-}" in
    launch) shift; cmd_launch "$@" ;;
    reattach) shift; cmd_reattach "$@" ;;
    verify) shift; cmd_verify "$@" ;;
    *) usage ;;
esac
