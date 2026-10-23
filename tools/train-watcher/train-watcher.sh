#!/usr/bin/env bash
# train-watcher.sh — 학습 종료 감시 → test eval 자동 실행 → 최종 보고(markdown) + ntfy 알림
# (2026-08-15 사용자 지시로 표준 템플릿화 — 학습 발사 시 부착, 재사용)
#
# 사용법 (학습 발사 직후, 같은 tmux pane 또는 nohup으로):
#   nohup bash ~/.claude/tools/train-watcher/train-watcher.sh \
#     --pid 12345 \
#     --log /path/train.log \
#     --done-regex 'Training (finished|complete)|`Trainer.fit` stopped' \
#     --eval-cmd 'CUDA_VISIBLE_DEVICES=4 uv run python eval.py --ckpt best.ckpt' \
#     --title 'exp A1' \
#     [--eval-log /path/eval.log] [--report /path/watch-report.md] \
#     [--interval 60] [--timeout-h 72] [--eval-timeout-h 12] [--no-notify] \
#     [--done-log '/path/run_*/train.log'] [--on-exit '<명령>'] \
#     > /path/watcher.log 2>&1 &
#
# --on-exit (2026-10-01, 대기 목록 자동 발사용): 아래 종료 코드 일곱 지점 모두에서 와쳐가 끝나기 직전에
#   WATCH_EXIT=<종료 코드> 환경으로 `bash -c '<명령>'` 을 한 번 실행한다(보고·알림이 끝난 뒤). 명령이 실패해도
#   와쳐 종료 코드는 그대로다. 인자 오류(64)에서는 부르지 않는다. 없으면 동작이 종전과 같다.
#   (명령은 launch-set.sh 가 대기 목록 도구로만 채운다 — 사용자가 --watcher-args 로 직접 주는 길은 거부된다.)
#
# --done-log (2026-09-29 사용자 결정): 완료 마커를 --log 대신 이 파일에서 찾는다. 글롭을 받으며, 일치하는
#   파일 중 와쳐 시작 뒤에 수정된 것 가운데 가장 최근 것을 쓴다(train_run_<시각>/ 처럼 경로가 실행 중에
#   정해지는 프로젝트 로그용, 옛 실행의 로그를 잘못 집지 않게 하려는 시각 조건). launch-set.sh 가 학습
#   표준출력을 창으로 돌리면 --log 에는 표준에러만 남아, 표준출력으로 찍히는 완료 마커를 거기서 못 찾는다.
#   memguard 발사 거부 판정·보고 꼬리는 계속 --log 를 본다. 없으면 종전처럼 --log 에서 찾는다.
#
# --eval-timeout-h (2026-10-01, D7): eval 이 이 시간(시간 단위, 소수 허용, 기본 12, 0=무제한)을 넘기면 eval 프로세스를
#   **죽이지 않고** 알림·보고만 남긴 뒤 종료 코드 6 으로 끝난다(--on-exit 도 6 으로 불린다). 멈춘 eval 하나가 종료 보고와
#   다음 판 발사를 무기한 막는 것을 끊되, 살아 있는 eval 이 쥔 GPU 는 비우지 않는다(대기 목록 도구가 6 을 «살아 있을 수 있음» 보류로 처리).
#
# 완료 마커 판정 범위 (2026-10-01): 와쳐가 시작할 때 학습 PID 가 살아 있었다면 마커는 그 시점의 파일 크기(바이트 위치) **뒤에
#   추가된 부분**에서만 찾는다 — 재사용한 로그에 남은 옛 실행의 성공 마커를 이번 실행의 완료로 오인해 크래시를 정상 완료로 보고하던 결함.
#   (파일이 그 뒤 줄어들면 처음부터 새 내용으로 본다.) 와쳐가 시작할 때 이미 PID 가 없었다면(와쳐보다 먼저 끝난 짧은 학습) 위치 제한 없이 찾고,
#   --done-log 시각 기준도 120초 앞까지 넓힌다.
#
# 메모리 압력 표본 (2026-10-12, intent/2026-10-12-host-memory-budget-and-pressure.md): 10-12 에 완료 마커 없이 끝난 판 둘이
#   systemd-oomd 의 압력 종료로 의심됐지만 종료 직전 압력 값이 어디에도 없어 확인이 안 됐다. 그래서 폴링마다 사용자 서비스 cgroup 의
#   memory.pressure `full avg10`·`avg60` 을 메모리 안 배열에 표본으로 잡고(최근 15개만, 파일 쓰기 없음), «완료 마커 없이 끝난 경우»의
#   보고서·알림에 직전 표본(최근 10개)과 판정 한 줄을 붙인다. 판정은 유지 중인 표본 전체 기준으로 full avg10 ≥ 25 또는 avg60 ≥ 15 가 있으면
#   «메모리 압력 종료(systemd-oomd) 의심 — 확정은 sudo journalctl -u systemd-oomd», 없으면 «종료 직전 메모리 압력 낮음(최대 avg10 X%)»,
#   표본이 하나도 없으면 «압력 표본 없음». 정상 종료·eval 경로·종료 코드는 그대로이고 와쳐는 학습을 죽이지 않는다.
#   시험용 틈: MEMGUARD_TEST_ROOT=<폴더> 가 있으면 그 아래 cgroup/memory.pressure 를 대신 읽는다(경고 줄을 표준에러에 낸다).
#
# 신호 (2026-10-01): TERM·INT 로 와쳐가 죽으면 종료 코드 7 로 보고·알림·--on-exit 를 한 번 실행하고 끝낸다(학습·eval 은 건드리지 않음).
#   예전에는 신호로 죽으면 종료 훅이 안 불려 대기 목록 사슬이 조용히 끊겼다. KILL(9)은 잡을 수 없다 — 대기 목록 도구의 wait-event 가
#   «와쳐가 죽은 도는 판»을 감시한다.
#
# 종료 코드: 0=학습 완료+eval 성공 / 2=학습 비정상 종료 의심(eval 미수행) /
#            3=eval 실패 / 4=감시 타임아웃(학습은 건드리지 않음) /
#            5=memguard 발사 거부 감지(학습 미시작 — 크래시 아님) /
#            6=eval 시간 초과(eval 은 죽이지 않음) / 7=TERM·INT 로 와쳐 중단 / 64=인자 오류
#
# 설계 제약 — 과거 실사고 3건이 인코딩된 부분이므로 수정 전 반드시 읽을 것:
#  1) 종료 감지는 PID(kill -0) 단독. ps|grep·pkill -f는 자기 명령줄 self-match로
#     허위 ABORT·self-kill을 낸 이력이 있어 금지.
#  2) 완료 판정은 "프로세스 종료 AND 로그 완료 마커" 둘 다 충족해야 한다. 마커가 없으면
#     eval을 돌리지 않는다 — 크래시를 '종료'로 오판해 epoch3 ckpt를 eval한 이력.
#  3) pipefail 아래 `장기실행 | grep -q`는 SIGPIPE로 성공을 실패로 오판한 이력 —
#     이 스크립트는 pipefail을 켜지 않으며 grep -q를 파이프에 걸지 않는다.
#  4) 학습 프로세스는 절대 죽이지 않는다. 타임아웃 시 알림만 하고 감시를 접는다.
#  5) 학습 "본 실행"은 여전히 사용자 직접(code-execution.md). 이 스크립트는 관찰과
#     eval(검증 목적 실행 예외)만 수행한다.
#  6) ntfy 호출은 stdout까지 버린다 — 터미널 벨이 로그에 BEL(0x07)로 섞여 파서를
#     깨뜨린 이력(2026-08-15 감사).

set -u

PID="" LOG="" DONE_RX="" EVAL_CMD="" TITLE="watch"
EVAL_LOG="" REPORT="" INTERVAL=60 TIMEOUT_H=72 NOTIFY=1 DONE_LOG="" ON_EXIT="" EVAL_TIMEOUT_H=12

while [ $# -gt 0 ]; do
    case "$1" in
        --pid)        PID="$2"; shift 2 ;;
        --log)        LOG="$2"; shift 2 ;;
        --done-regex) DONE_RX="$2"; shift 2 ;;
        --eval-cmd)   EVAL_CMD="$2"; shift 2 ;;
        --title)      TITLE="$2"; shift 2 ;;
        --eval-log)   EVAL_LOG="$2"; shift 2 ;;
        --report)     REPORT="$2"; shift 2 ;;
        --interval)   INTERVAL="$2"; shift 2 ;;
        --timeout-h)  TIMEOUT_H="$2"; shift 2 ;;
        --eval-timeout-h) EVAL_TIMEOUT_H="$2"; shift 2 ;;
        --no-notify)  NOTIFY=0; shift ;;
        --done-log)   DONE_LOG="$2"; shift 2 ;;
        --on-exit)    ON_EXIT="$2"; shift 2 ;;
        *) echo "알 수 없는 인자: $1" >&2; exit 64 ;;
    esac
done

if [ -z "$PID" ] || [ -z "$LOG" ] || [ -z "$DONE_RX" ] || [ -z "$EVAL_CMD" ]; then
    echo "필수 인자: --pid --log --done-regex --eval-cmd (선택: --title --eval-log --report --interval --timeout-h --eval-timeout-h --no-notify --done-log --on-exit)" >&2
    exit 64
fi
case "$PID" in *[!0-9]*) echo "--pid는 숫자여야 함: $PID" >&2; exit 64 ;; esac
# 숫자 검증(2026-10-01): --interval 이 0·비숫자면 `sleep` 이 즉시 실패해 PID 감시 루프가 CPU 를 태우고, --timeout-h 가 비숫자면 산술이 깨진다.
case "$INTERVAL" in ''|*[!0-9]*|0) echo "--interval 은 1 이상의 정수(초): $INTERVAL" >&2; exit 64 ;; esac
case "$TIMEOUT_H" in ''|*[!0-9]*) echo "--timeout-h 는 0 이상의 정수(시간): $TIMEOUT_H" >&2; exit 64 ;; esac
case "$EVAL_TIMEOUT_H" in ''|.|*[!0-9.]*|*.*.*) echo "--eval-timeout-h 는 0 이상의 수(시간, 소수 허용, 0=무제한): $EVAL_TIMEOUT_H" >&2; exit 64 ;; esac
# --done-log 시각 기준 = 학습 프로세스 시작 시각(경과 초로 역산, 2초 여유). 와쳐 시작 시각을 쓰면 와쳐보다 먼저
# 끝난 짧은 학습의 마커를 놓친다(2026-09-29 시험). PID 가 이미 없으면 시작 시각을 알 수 없어 120초 전까지 넓혀 잡는다(2026-10-01:
# 예전에는 «지금 -2초» 라 와쳐가 뜨기 직전에 끝난 학습의 마커 파일이 조건에서 빠져 정상 완료가 크래시로 보고됐다. 오탐 쪽이 보수적이다).
PID_GONE=0
_et=$(ps -o etimes= -p "$PID" 2>/dev/null | tr -d ' ')
case "$_et" in ''|*[!0-9]*) _et=0; PID_GONE=1 ;; esac
START_EPOCH=$(( $(date +%s) - _et - 2 ))
[ "$PID_GONE" = 1 ] && START_EPOCH=$(( $(date +%s) - 120 ))
[ -z "$EVAL_LOG" ] && EVAL_LOG="${LOG%.log}.eval.log"
[ -z "$REPORT" ] && REPORT="${LOG%.log}.watch-report.md"

notify() {  # $1=메시지 — 제약 6: stdout·stderr 전부 버림
    [ "$NOTIFY" -eq 1 ] || return 0
    bash "$HOME/.claude/scripts/claude-notify.sh" "train-watcher" "$1" >/dev/null 2>&1 || true
}
ts() { date '+%Y-%m-%d %H:%M:%S'; }
log_w() { echo "[$(ts)] [watcher] $*"; }
FINISHING=0 FINISH_CODE=7
finish() {  # $1=종료 코드 — --on-exit 가 있으면 WATCH_EXIT 와 함께 한 번 실행한 뒤 같은 코드로 끝낸다
    FINISHING=1; FINISH_CODE="$1"   # 종료 중(on-exit 실행 중) 신호가 와도 on-exit 를 두 번 부르지 않는다 — on_signal 참조
    if [ -n "$ON_EXIT" ]; then
        log_w "on-exit 실행 (WATCH_EXIT=$1)"
        WATCH_EXIT="$1" bash -c "$ON_EXIT" || log_w "on-exit 실패 (exit $?) — 와쳐 종료 코드는 그대로"
    fi
    exit "$1"
}

# 대기: 전경 `sleep` 은 끝날 때까지 trap 이 미뤄지므로 백그라운드로 돌리고 wait 로 기다린다(신호가 오면 wait 가 곧바로 깨어 trap 이 돈다).
NAP_PID=""
nap() { sleep "$1" & NAP_PID=$!; wait "$NAP_PID" 2>/dev/null; }
on_signal() {  # $1=신호 이름 — 와쳐만 접는다. 학습·eval 은 건드리지 않는다(제약 4)
    [ -n "$NAP_PID" ] && kill "$NAP_PID" 2>/dev/null
    [ "$FINISHING" = 1 ] && exit "$FINISH_CODE"
    log_w "신호 $1 수신 — 와쳐 중단(학습·eval 은 건드리지 않음)"
    write_report "⚠ 와쳐가 신호($1)로 중단됨 (학습·eval 은 계속 중일 수 있음)" "" ""
    notify "[${TITLE}] 와쳐가 신호($1)로 중단됨 — 학습은 계속 중일 수 있음. 보고: ${REPORT}"
    finish 7
}

file_size() { stat -c %s "$1" 2>/dev/null || echo 0; }
# 완료 마커 판정 범위(헤더 «완료 마커 판정 범위»): 시작 시점 파일 크기. PID 가 이미 없던 경우는 비워 둔다(= 처음부터).
declare -A START_OFFSET
if [ "$PID_GONE" = 0 ]; then
    START_OFFSET["$LOG"]=$(file_size "$LOG")
    if [ -n "$DONE_LOG" ]; then
        shopt -s nullglob
        # shellcheck disable=SC2086
        for _f in $DONE_LOG; do [ -f "$_f" ] && START_OFFSET["$_f"]=$(file_size "$_f"); done   # 의도적 비인용: 글롭 전개
        shopt -u nullglob
    fi
fi

find_marker() {  # $1=파일 — 시작 위치 뒤에 추가된 부분의 마지막 500줄에서 마지막 마커 줄. 없으면 빈 문자열
    local off="${START_OFFSET[$1]:-0}" size
    size=$(file_size "$1")
    [ "$size" -lt "$off" ] && off=0   # 시작 뒤 파일이 줄었다(다시 만들어짐) — 전부 새 내용
    tail -c +"$((off + 1))" "$1" 2>/dev/null | tail -n 500 | grep -E "$DONE_RX" | tail -1
}

resolve_done_file() {  # --done-log 글롭 중 와쳐 시작 뒤 수정된 가장 최근 파일. 없으면 빈 문자열
    local best="" best_m=0 f m
    shopt -s nullglob
    # shellcheck disable=SC2086
    for f in $DONE_LOG; do   # 의도적 비인용: 글롭 전개
        [ -f "$f" ] || continue
        m=$(stat -c %Y "$f" 2>/dev/null) || continue
        [ "$m" -ge "$START_EPOCH" ] || continue
        if [ "$m" -gt "$best_m" ]; then best="$f"; best_m="$m"; fi
    done
    shopt -u nullglob
    printf '%s' "$best"
}
DONE_FILE=""

# 메모리 압력 표본 (헤더 «메모리 압력 표본»): 폴링마다 "HH:MM:SS avg10 avg60" 한 줄, 최근 15개만 메모리에 유지한다.
PSI_FILE="/sys/fs/cgroup/user.slice/user-$(id -u).slice/user@$(id -u).service/memory.pressure"
if [ -n "${MEMGUARD_TEST_ROOT:-}" ]; then
    PSI_FILE="$MEMGUARD_TEST_ROOT/cgroup/memory.pressure"
    echo "[watcher] 경고: 시험용 경로 사용 중 (MEMGUARD_TEST_ROOT=$MEMGUARD_TEST_ROOT)" >&2
fi
PSI_SAMPLES=()
PSI_NOTE=""   # 완료 마커 없이 끝났을 때만 채워지는 보고서·알림용 문구
sample_psi() {  # 읽지 못하면 표본을 만들지 않는다
    local a b n
    read -r a b < <(awk '$1=="full"{for(i=2;i<=NF;i++){split($i,k,"=");if(k[1]=="avg10")x=k[2];if(k[1]=="avg60")y=k[2]}} END{if(x!=""&&y!="")print x, y}' "$PSI_FILE" 2>/dev/null) || true
    case "${a:-}${b:-}" in ''|*[!0-9.]*) return 0 ;; esac
    PSI_SAMPLES+=("$(date +%H:%M:%S) $a $b")
    n=${#PSI_SAMPLES[@]}
    [ "$n" -gt 15 ] && PSI_SAMPLES=("${PSI_SAMPLES[@]:$(( n - 15 ))}")
    return 0
}
psi_verdict() {  # 표본 전체로 판정 한 줄
    if [ "${#PSI_SAMPLES[@]}" -eq 0 ]; then echo "압력 표본 없음"; return 0; fi
    printf '%s\n' "${PSI_SAMPLES[@]}" | awk '{ if ($2+0 > m10) m10 = $2+0; if ($3+0 > m60) m60 = $3+0 }
        END { if (m10 >= 25 || m60 >= 15) print "메모리 압력 종료(systemd-oomd) 의심 — 확정은 sudo journalctl -u systemd-oomd";
              else printf "종료 직전 메모리 압력 낮음(최대 avg10 %s%%)\n", m10 + 0 }'
}
psi_note() {  # 보고서 절 본문: 직전 표본 최근 10개 + 판정 한 줄
    local n=${#PSI_SAMPLES[@]} start=0 s a b t
    [ "$n" -gt 10 ] && start=$(( n - 10 ))
    if [ "$n" -gt 0 ]; then
        for s in "${PSI_SAMPLES[@]:$start}"; do
            read -r t a b <<< "$s"
            echo "- $t full avg10=${a}% avg60=${b}%"
        done
        echo
    fi
    echo "판정: $(psi_verdict)"
}

write_report() {  # $1=판정 $2=완료마커 $3=eval종료코드
    {
        echo "# 학습 와치 최종 보고 — ${TITLE}"
        echo
        echo "| 항목 | 값 |"
        echo "|---|---|"
        echo "| 판정 | $1 |"
        echo "| 학습 PID | ${PID} |"
        echo "| 학습 로그 | ${LOG} |"
        echo "| 완료 마커 파일 | ${DONE_FILE:-${DONE_LOG:+(일치 파일 없음: ${DONE_LOG})}} |"
        echo "| 완료 마커 | ${2:-없음} |"
        echo "| eval 명령 | \`${EVAL_CMD}\` |"
        echo "| eval 종료 코드 | ${3:-미실행} |"
        echo "| eval 로그 | ${EVAL_LOG} |"
        echo "| 보고 생성 | $(ts) |"
        echo
        if [ -n "$PSI_NOTE" ]; then
            echo "## 메모리 압력 표본 (종료 직전 최근 10개, 사용자 서비스 cgroup)"
            echo "$PSI_NOTE"
            echo
        fi
        if [ -f "$EVAL_LOG" ]; then
            echo "## eval 로그 꼬리 (마지막 40줄)"
            echo '```'
            tail -n 40 "$EVAL_LOG"
            echo '```'
        fi
        echo
        echo "## 학습 로그 꼬리 (마지막 15줄)"
        echo '```'
        tail -n 15 "$LOG" 2>/dev/null || echo "(로그 읽기 실패)"
        echo '```'
    } > "$REPORT"
    log_w "보고 저장: $REPORT"
}

trap 'on_signal TERM' TERM   # write_report·finish 가 정의된 뒤에 건다
trap 'on_signal INT' INT

log_w "감시 시작 — PID=${PID}, 로그=${LOG}, 폴링=${INTERVAL}s, 타임아웃=${TIMEOUT_H}h, eval 시간 제한=${EVAL_TIMEOUT_H}h"
DEADLINE=$(( $(date +%s) + TIMEOUT_H * 3600 ))

# 제약 1: PID 단독 감시. kill -0은 시그널을 보내지 않는다(존재 확인만).
while kill -0 "$PID" 2>/dev/null; do
    sample_psi
    if [ "$(date +%s)" -ge "$DEADLINE" ]; then
        log_w "타임아웃(${TIMEOUT_H}h) — 학습은 계속 실행 중, 감시만 종료 (제약 4)"
        write_report "⏱ 감시 타임아웃 (학습 계속 중 — 와쳐만 종료)" "" ""
        notify "[${TITLE}] 와쳐 타임아웃 ${TIMEOUT_H}h — 학습은 계속 중, 감시만 종료. 보고: ${REPORT}"
        finish 4
    fi
    nap "$INTERVAL"
done

log_w "학습 프로세스 종료 감지 — 로그 flush 대기 10s"
nap 10

# 제약 2·3: 완료 마커를 파일 대상 grep으로 직접 확인 (grep -q 파이프 금지)
if [ -n "$DONE_LOG" ]; then
    DONE_FILE="$(resolve_done_file)"
    log_w "완료 마커 파일: ${DONE_FILE:-일치 파일 없음 (${DONE_LOG}, 와쳐 시작 뒤 수정분만)}"
else
    DONE_FILE="$LOG"
fi
MARKER=""
[ -n "$DONE_FILE" ] && MARKER=$(find_marker "$DONE_FILE")
if [ -z "$MARKER" ]; then
    # memguard 발사 거부(exit 75/77)는 크래시가 아니다 — 거부 메시지가 같은 로그(stderr 합류)에
    # 남으므로 구분 보고 (2026-08-19 검수 발견: 뭉뚱그리면 "예산 부족 미발사"를 크래시로 오판)
    REFUSED=$(tail -n 50 "$LOG" 2>/dev/null | grep -F '[memguard]' | grep -E '거부|불가' | tail -1)
    if [ -n "$REFUSED" ]; then
        log_w "memguard 발사 거부 감지 — 학습이 시작되지 않음 (크래시 아님)"
        write_report "🟡 발사 거부 (memguard preflight/강제불가 — 학습 미시작)" "$REFUSED" ""
        notify "[${TITLE}] 학습 발사 거부(memguard) — ${REFUSED}"
        finish 5
    fi
    log_w "완료 마커 부재 — 비정상 종료 의심, eval 미수행 (제약 2)"
    PSI_NOTE="$(psi_note)"
    log_w "메모리 압력 판정: $(psi_verdict)"
    write_report "🔴 학습 비정상 종료 의심 (완료 마커 부재 — eval 미수행)" "" ""
    notify "[${TITLE}] 학습 비정상 종료 의심 — 완료 마커 없음, eval 미수행. 압력: $(psi_verdict). 로그: ${LOG}"
    finish 2
fi

log_w "완료 마커 확인: ${MARKER}"
log_w "test eval 시작 → ${EVAL_LOG} (시간 제한 ${EVAL_TIMEOUT_H}h, 0=무제한)"
# eval 은 백그라운드로 돌려 시간 제한을 걸 수 있게 한다(종전엔 전경 실행이라 멈추면 와쳐도 영원히 멈춰 종료 보고·다음 판 발사가 중단됐다).
# 시간 초과여도 eval 을 죽이지 않는다 — 살아 있는 eval 이 GPU 를 쓰고 있을 수 있다(D7).
bash -c "$EVAL_CMD" > "$EVAL_LOG" 2>&1 &
EVAL_PID=$!
EVAL_TIMEOUT_S=$(awk -v h="$EVAL_TIMEOUT_H" 'BEGIN{s=int(h*3600); if (h>0 && s<1) s=1; print s}')
EVAL_DEADLINE=$(( $(date +%s) + EVAL_TIMEOUT_S ))
EVAL_POLL=$INTERVAL; [ "$EVAL_POLL" -gt 5 ] && EVAL_POLL=5
while kill -0 "$EVAL_PID" 2>/dev/null; do
    if [ "$EVAL_TIMEOUT_S" -gt 0 ] && [ "$(date +%s)" -ge "$EVAL_DEADLINE" ]; then
        log_w "eval 시간 초과(${EVAL_TIMEOUT_H}h) — eval(PID ${EVAL_PID})은 죽이지 않고 알림 후 감시 종료"
        write_report "⏱ eval 시간 초과 (${EVAL_TIMEOUT_H}h — eval 프로세스 ${EVAL_PID} 는 계속 실행 중)" "$MARKER" ""
        notify "[${TITLE}] eval 이 ${EVAL_TIMEOUT_H}h 를 넘겨 멈춘 것으로 보임 — eval(PID ${EVAL_PID})은 죽이지 않았고 GPU 는 보류됩니다. 로그: ${EVAL_LOG}"
        finish 6
    fi
    nap "$EVAL_POLL"
done
wait "$EVAL_PID"
EC=$?
log_w "eval 종료 (exit ${EC})"

if [ "$EC" -eq 0 ]; then
    write_report "✅ 학습 완료 + eval 성공" "$MARKER" "$EC"
    notify "[${TITLE}] 학습 완료 + test eval 성공 ✅ 최종 보고: ${REPORT}"
    finish 0
else
    write_report "🔴 eval 실패 (exit ${EC})" "$MARKER" "$EC"
    notify "[${TITLE}] 학습은 완료됐으나 eval 실패(exit ${EC}) — 로그: ${EVAL_LOG}"
    finish 3
fi
