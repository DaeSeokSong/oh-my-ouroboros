#!/usr/bin/env bash
# memguard-run.sh — 학습·추론 실행을 user cgroup 메모리 한도로 감싸는 래퍼
# (2026-08-18 OOM발 SSH 장애 후속 — sudo 불필요, systemd user scope 사용)
#
# 사용법:
#   memguard-run.sh [--high 40G] [--max 56G] [--reserve 32G] [--swap-max auto] [--name tag] \
#                   [--pressure-max 10] [--preflight-only] [--allow-unenforced] -- <명령> [인자...]
# 예:
#   bash ~/.claude/tools/mem-guard/memguard-run.sh --name exp-a1 -- \
#     env CUDA_VISIBLE_DEVICES=0 uv run python train.py --config-name=train
#
# 동작:
#   1) preflight — (MemAvailable − Σ 안 자란 몫) ≥ (OS 예약 --reserve, 기본 32G) + (작업 예산 = --max)
#      을 충족하지 못하면 실행 거부 (exit 75). Swap 고갈은 경고만.
#      ★안 자란 몫 (2026-10-12 실사고): 판마다 memory.high 까지 자라므로, 발사 시점의 MemAvailable 만으로는
#        «이미 도는 판들이 앞으로 더 쓸 양»을 못 본다. 동시에 도는 판들의 high 합이
#        서버 메모리를 넘었고(남은 양 < 안 자란 몫), 그 상태에서 두 판이 systemd-oomd 압력
#        종료로 끝났다. 그래서 같은 계정(user@<uid>.service)의 모든 memguard-*.scope(재귀)에서
#        Σ max(memory.high − memory.current, 0) 을 구해 MemAvailable 에서 뺀다. memory.high 가 숫자가 아닌
#        (max) scope 는 건너뛴다. 사용자 서비스 cgroup 뿌리를 못 읽으면 종전 검사만 하고 경고 한 줄.
#        (거부 메시지에 남은 메모리·안 자란 몫·예약·예산이 GiB 로 나온다.)
#      ★빈 scope 제외 (2026-10-17 실사고): 끝난 판의 scope 가 `systemctl --user` 에서 «loaded active running» 으로 남는다
#        (--collect 를 줘도 그렇다. 7개가 남았고 프로세스는 cgroup 하위 전체에 0개였다. 같은 날 임시 scope 로 재현:
#        자식이 exit 7 로 끝난 뒤에도 scope 가 active 로 남고 exit code 만 정상 전달된다). 그 scope 의 memory.high − memory.current
#        가 «안 자란 몫» 에 계속 더해져 새 발사가 전부 거부(exit 75)됐다. 그래서 cgroup 하위 전체의 cgroup.procs 줄 수
#        합이 0 인 scope 는 합산에서 빼고 개수를 메시지에 «빈 scope N개 제외» 로 낸다. 읽다가 실패한 cgroup.procs 는 비어 있지
#        않은 것으로 본다(예산을 낙관하지 않는 쪽으로 틀린다). 프로세스가 있는 scope 는 종전 그대로 high − current 를 더한다.
#      예약 64G→32G (2026-09-29 사용자 결정): GPU 마다 한 판씩 동시에 올리기 위함.
#      판 예산은 실측에 맞춰 --high/--max 로 따로 준다(예: --high 34G --max 40G).
#   1b) 압력 검사 (2026-10-12) — 같은 뿌리의 memory.pressure 에서 `full avg60` 이 --pressure-max(퍼센트, 기본 10,
#      0 이면 끔) 이상이면 거부 (exit 75, 메시지에 값과 문턱). 파일을 못 읽으면 경고만 내고 통과.
#   1c) 거부 알림 (2026-10-12 사용자 지시) — 예산·압력 거부로 «실제 발사»가 막히면 claude-notify.sh 로 🚫 알림 1회.
#      --preflight-only(점검) 호출은 알리지 않는다. launch-set.sh 는 점검 호출 없이 이 스크립트를 본 실행으로 부르므로
#      거부 알림이 발사 시도당 한 번만 간다.
#   2) systemd-run --user --scope -p MemoryHigh -p MemoryMax -p MemorySwapMax 로 실행.
#      --swap-max (2026-09-29 사용자 결정 «상한만, 하한 없음»): 기본 auto = SwapTotal ÷ GPU 수.
#      상한이 없으면 먼저 MemoryHigh 에 닿은 판이 swap 을 독차지한다.
#      하한(보장)은 두지 않는다 — cgroup v2 에는 swap 하한 설정도 없다.
#      none/infinity = 상한 없음(종전 동작). GPU 를 못 세면(nvidia-smi 없음) auto 도 상한 없음.
#      scope는 cgroup이므로 fork·setsid 된 자식 전부가 같은 한도 안에 있다.
#      MemoryHigh 초과 시 커널이 해당 그룹만 강한 회수(스로틀), MemoryMax 초과 시
#      그 그룹 안에서만 OOM kill → 호스트 전역(OOM→sshd 마비) 재발 방지.
#   2b) 자가 정리 (2026-10-17, 환경변수 MEMGUARD_SELF_STOP=0 이면 끔, 기본 1; --name 이 있을 때만) — 위 «빈 scope» 가 남는 것 자체를 막는다.
#      ★설계 선택: scope 안에서 `bash -c '"$@"; systemctl stop'` 로 감싸는 방안과 exec 를 버리고 자식으로 돌리는 방안은 쓰지 않았다.
#        둘 다 launch-set.sh 가 `$!` 로 기록하는 PID 가 학습 프로세스가 아니라 감싸는 bash(또는 memguard-run.sh)가 되어,
#        ① 그 PID 에 보낸 SIGTERM·SIGKILL 이 학습에 닿지 않고(감싼 bash 만 죽고 학습은 scope 안에 고아로 남는다),
#        ② train-watcher.sh 의 kill -0 감시·launch-set.sh 의 argv·exe·starttime 검증이 학습 아닌 프로세스를 가리키며,
#        ③ background-task.md 가 보증하는 «exec 체인 불변식($! = 학습 PID)» 이 깨진다.
#        그래서 exec 는 그대로 두고, exec 직전에 scope 밖(호출자 cgroup)에 작은 감시 서브셸을 하나 띄운다. 이 서브셸은
#        ① 이 스크립트의 PID(=exec 뒤 학습 PID)가 사라질 때까지(좀비 포함, starttime 으로 PID 재사용 구분) 기다리고
#        ② scope 의 cgroup 하위 전체에 남은 프로세스가 0개가 되면 `systemctl --user stop <unit>.scope` 를 한 번 하고 끝난다.
#        scope 가 이미 없으면(수거됨·systemd-run 실패) 아무것도 하지 않는다. 자식이 고아로 남겨 둔 워커가 있으면 그것이 끝날 때까지
#        기다린다(살아 있는 프로세스를 stop 으로 죽이지 않는다). 확인: 임시 scope 실측에서 exec 전에 띄운 서브셸은 session scope 에 남고
#        학습만 새 scope 로 옮겨졌다. 점검 주기는 MEMGUARD_STOP_POLL 초(기본 5, 시험용).
#   3) user 위임이 없어 강제가 불가한 호스트에서는 기본 거부하고 관리자 조치를
#      안내한다. --allow-unenforced 를 준 경우에만 한도 없이 그대로 실행.
#
# 시험용 틈: 환경변수 MEMGUARD_TEST_ROOT=<폴더> 가 있으면 그 아래 `meminfo` 와 `cgroup/` 나무를 /proc/meminfo·
#   사용자 서비스 cgroup 대신 읽는다(--preflight-only 로 전부 시험 가능). 켜져 있으면 표준에러에 경고 줄을 반드시 낸다.
#   본 실행 경로의 위임 검사(cgroup.controllers)도 이 나무의 `cgroup/cgroup.controllers` 를 읽고, systemd-run·systemctl 은 PATH 의
#   가짜로 대체해 시험한다(실제 systemd 를 건드리지 않는다).
#
# 검증 근거 (2026-08-18 실측): cgroup2fs + systemd 249,
#   user@1002.service cgroup.controllers = "memory pids" → 테스트 scope에서
#   memory.max/high 적용 확인. 판정 exit 코드: 0=정상 종료(감쌈), 75=preflight 거부(메모리 예산·압력),
#   77=강제 불가(미허용), 그 외=감싼 명령의 exit code 전달.

set -u

HIGH="40G"; MAX="56G"; RESERVE="32G"; SWAP_MAX="auto"; NAME=""; PREFLIGHT_ONLY=0; ALLOW_UNENFORCED=0; PRESSURE_MAX="10"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="$DIR/memguard.log"

to_kb() {  # "40G"/"512M"/"1000000K"/순수숫자(바이트) → kB
    local v="${1^^}" n
    case "$v" in
        *G) n="${v%G}"; echo $(( n * 1024 * 1024 )) ;;
        *M) n="${v%M}"; echo $(( n * 1024 )) ;;
        *K) n="${v%K}"; echo "${v%K}" ;;
        *[!0-9]*) echo "잘못된 크기: $1" >&2; return 1 ;;
        *) echo $(( v / 1024 )) ;;
    esac
}

while [ $# -gt 0 ]; do
    case "$1" in
        --high) HIGH="$2"; shift 2 ;;
        --max) MAX="$2"; shift 2 ;;
        --reserve) RESERVE="$2"; shift 2 ;;
        --swap-max) SWAP_MAX="$2"; shift 2 ;;
        --name) NAME="$2"; shift 2 ;;
        --pressure-max) PRESSURE_MAX="$2"; shift 2 ;;
        --preflight-only) PREFLIGHT_ONLY=1; shift ;;
        --allow-unenforced) ALLOW_UNENFORCED=1; shift ;;
        --) shift; break ;;
        *) echo "알 수 없는 인자: $1 (사용법은 파일 헤더)" >&2; exit 64 ;;
    esac
done

# --name 은 unit 이름과 find -name 패턴에 쓰이므로 글롭·공백 문자를 막는다(2026-10-17)
if [ -n "$NAME" ] && [[ ! "$NAME" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "--name 은 영문·숫자·. _ - 만 허용합니다: $NAME" >&2; exit 64
fi
if [ $PREFLIGHT_ONLY -eq 0 ] && [ $# -eq 0 ]; then
    echo "실행할 명령이 없습니다: ... -- <명령> [인자]" >&2; exit 64
fi
case "$PRESSURE_MAX" in ''|.*|*.|*[!0-9.]*|*.*.*) echo "--pressure-max 는 0 이상의 수(퍼센트, 0=끔): $PRESSURE_MAX" >&2; exit 64 ;; esac

# 읽을 곳: 실제 서버 값 또는 시험용 나무(MEMGUARD_TEST_ROOT)
MEMINFO=/proc/meminfo
CG_ROOT="/sys/fs/cgroup/user.slice/user-$(id -u).slice/user@$(id -u).service"
if [ -n "${MEMGUARD_TEST_ROOT:-}" ]; then
    MEMINFO="$MEMGUARD_TEST_ROOT/meminfo"; CG_ROOT="$MEMGUARD_TEST_ROOT/cgroup"
    echo "[memguard] 경고: 시험용 경로 사용 중 (MEMGUARD_TEST_ROOT=$MEMGUARD_TEST_ROOT) — 실제 서버 값이 아닙니다" >&2
fi

HIGH_KB=$(to_kb "$HIGH") || exit 64
MAX_KB=$(to_kb "$MAX") || exit 64
RESERVE_KB=$(to_kb "$RESERVE") || exit 64
# swap 상한 → SWAP_PROP (빈 값 = 속성을 넘기지 않음 = 무제한)
SWAP_PROP=""
case "${SWAP_MAX,,}" in
    none|infinity) ;;
    auto)
        ST_KB=$(awk '/^SwapTotal:/{print $2}' "$MEMINFO")
        NGPU=$(nvidia-smi -L 2>/dev/null | grep -c '^GPU ' || true)
        if [ "${ST_KB:-0}" -gt 0 ] && [ "${NGPU:-0}" -gt 0 ]; then
            SWAP_PROP="$(( ST_KB / NGPU ))K"
        fi ;;
    *) to_kb "$SWAP_MAX" >/dev/null || exit 64; SWAP_PROP="$SWAP_MAX" ;;
esac
if [ "$HIGH_KB" -gt "$MAX_KB" ]; then
    echo "MemoryHigh($HIGH) > MemoryMax($MAX) — high는 max 이하여야 합니다" >&2; exit 64
fi

# ── preflight: (MemAvailable − Σ 안 자란 몫) ≥ reserve + 작업 예산(max) ───────
AVAIL_KB=$(awk '/^MemAvailable:/{print $2}' "$MEMINFO")
NEED_KB=$(( RESERVE_KB + MAX_KB ))
gib() { awk -v k="$1" 'BEGIN{printf "%.1f", k/1048576}'; }
scope_nprocs() {  # $1=scope 폴더 → cgroup 하위 전체 cgroup.procs 줄 수 합. find·읽기가 하나라도 실패하면 1(비어 있지 않은 것으로 본다)
    local n=0 f c list
    list=$(find "$1" -name cgroup.procs 2>/dev/null) || { echo 1; return; }
    while IFS= read -r f; do
        [ -n "$f" ] || continue
        c=$(wc -l < "$f" 2>/dev/null) || { echo 1; return; }
        n=$(( n + c ))
    done <<< "$list"
    echo "$n"
}
# 거부 알림 (2026-10-12 사용자 지시: 메모리 때문에 «실제 발사»가 거부될 때만 한 번). 점검용 --preflight-only 는 알리지 않는다.
# mem-watch.sh 의 send() 와 같은 방식(claude-notify.sh direct 경로, 출력 버림, 스크립트 없으면 조용히 건너뜀, 실패해도 exit 75 불변).
# 이름이 없으면 명령 첫 낱말의 파일 이름만 쓴다. 첫 낱말이 `KEY=값` 꼴이면 값이 알림에 실리지 않게 «(이름 없음)» 으로 둔다.
LABEL="${NAME:-$(basename -- "${1:-?}")}"
case "$LABEL" in *=*) LABEL="(이름 없음)" ;; esac
notify_refusal() {  # $1=거부 사유 한 줄
    local n="$DIR/../../scripts/claude-notify.sh"
    [ $PREFLIGHT_ONLY -eq 0 ] && [ -f "$n" ] || return 0
    # timeout 10: 알림이 멈춰도 거부 종료(exit 75)가 늦어지지 않게 한다(2026-10-12 검수: 제한이 없으면 알림 지연만큼 발사 창이 멈춘다).
    timeout 10 bash "$n" "memguard" "🚫 [memguard $(hostname)] 발사 거부(메모리): ${LABEL} — $1" </dev/null >/dev/null 2>&1 || true
}

# 안 자란 몫: 사용자 서비스 cgroup 아래 모든 memguard-*.scope 의 max(high − current, 0) 합. high 가 숫자가 아니면(max) 건너뛴다.
# 프로세스가 0개인 빈 scope(끝난 판의 껍데기, 2026-10-17)도 건너뛰고 NEMPTY 로 센다.
ROOM_B=0; NSCOPE=0; NEMPTY=0; CG_READ=0
if [ -d "$CG_ROOT" ] && [ -r "$CG_ROOT" ]; then
    CG_READ=1
    while IFS= read -r -d '' sc; do
        hi=""; cu=""
        { read -r hi < "$sc/memory.high"; } 2>/dev/null || true
        { read -r cu < "$sc/memory.current"; } 2>/dev/null || true
        case "$hi" in ''|*[!0-9]*) continue ;; esac
        case "$cu" in ''|*[!0-9]*) continue ;; esac
        [ "$(scope_nprocs "$sc")" -eq 0 ] && { NEMPTY=$(( NEMPTY + 1 )); continue; }
        NSCOPE=$(( NSCOPE + 1 ))
        [ "$hi" -gt "$cu" ] && ROOM_B=$(( ROOM_B + hi - cu ))
    done < <(find "$CG_ROOT" -type d -name 'memguard-*.scope' -prune -print0 2>/dev/null)
fi
ROOM_KB=$(( ROOM_B / 1024 ))
if [ $CG_READ -eq 0 ]; then
    echo "[memguard] 경고: 사용자 서비스 cgroup 뿌리($CG_ROOT)를 읽지 못해 안 자란 몫 없이 종전 검사만 합니다" >&2
fi
BUDGET_KB=$(( AVAIL_KB - ROOM_KB ))
if [ "$BUDGET_KB" -lt "$NEED_KB" ]; then
    REASON="남은 메모리 $(gib "$AVAIL_KB")GiB − 안 자란 몫 $(gib "$ROOM_KB")GiB(scope ${NSCOPE}개) · 빈 scope ${NEMPTY}개 제외 = $(gib "$BUDGET_KB")GiB < 필요 $(gib "$NEED_KB")GiB (OS 예약 $(gib "$RESERVE_KB") + 작업 예산 $(gib "$MAX_KB"))"
    echo "[memguard] 거부: $REASON" >&2
    echo "[memguard] 조치: 예산(--max)을 줄이거나 다른 판 종료 후 재시도" >&2
    notify_refusal "$REASON"
    exit 75
fi

# 압력 검사: 사용자 서비스 cgroup 의 memory.pressure `full avg60`(%). 0 이면 끔, 못 읽으면 경고만.
PRESS_DESC="압력 검사 끔"
if [ "$PRESSURE_MAX" != "0" ] && awk -v m="$PRESSURE_MAX" 'BEGIN{exit !(m+0>0)}'; then
    PRESS60=$(awk '$1=="full"{for(i=2;i<=NF;i++) if($i ~ /^avg60=/){sub("avg60=","",$i); print $i}}' "$CG_ROOT/memory.pressure" 2>/dev/null | head -n 1)
    case "$PRESS60" in
        ''|*[!0-9.]*)
            echo "[memguard] 경고: $CG_ROOT/memory.pressure 를 읽지 못해 압력 검사를 건너뜁니다" >&2
            PRESS_DESC="압력 읽기 실패" ;;
        *)
            if awk -v p="$PRESS60" -v m="$PRESSURE_MAX" 'BEGIN{exit !(p+0>=m+0)}'; then
                REASON="메모리 압력 full avg60 ${PRESS60}% ≥ 문턱 ${PRESSURE_MAX}% (--pressure-max)"
                echo "[memguard] 거부: $REASON" >&2
                echo "[memguard] 조치: 압력이 가라앉은 뒤 재시도하거나 도는 판을 줄이세요" >&2
                notify_refusal "$REASON"
                exit 75
            fi
            PRESS_DESC="압력 full avg60 ${PRESS60}% < ${PRESSURE_MAX}%" ;;
    esac
fi
SWAP_TOTAL=$(awk '/^SwapTotal:/{print $2}' "$MEMINFO")
SWAP_FREE=$(awk '/^SwapFree:/{print $2}' "$MEMINFO")
if [ "$SWAP_TOTAL" -gt 0 ] && [ "$SWAP_FREE" -lt $(( SWAP_TOTAL / 10 )) ]; then
    echo "[memguard] 경고: Swap 잔여 10% 미만 ($(gib "$SWAP_FREE")GiB/$(gib "$SWAP_TOTAL")GiB) — 한도 도달 시 회수 여지가 적음" >&2
fi
SWAP_DESC="무제한"; [ -n "$SWAP_PROP" ] && SWAP_DESC="$(gib "$(to_kb "$SWAP_PROP")")GiB"
echo "[memguard] preflight PASS: MemAvailable $(gib "$AVAIL_KB")GiB − 안 자란 몫 $(gib "$ROOM_KB")GiB(scope ${NSCOPE}개) · 빈 scope ${NEMPTY}개 제외 = $(gib "$BUDGET_KB")GiB ≥ 예약 $(gib "$RESERVE_KB") + 예산 $(gib "$MAX_KB") ($PRESS_DESC, swap 상한 $SWAP_DESC)"
[ $PREFLIGHT_ONLY -eq 1 ] && exit 0

# ── 강제 가능 여부 (user 위임 memory 컨트롤러) ─────────────────────────────
CTRL_FILE="$CG_ROOT/cgroup.controllers"   # 실제 서버에서는 종전 경로와 같고, 시험(MEMGUARD_TEST_ROOT)에서는 가짜 나무를 읽는다
ENFORCEABLE=0
if [ -r "$CTRL_FILE" ] && grep -qw memory "$CTRL_FILE" && command -v systemd-run >/dev/null 2>&1; then
    ENFORCEABLE=1
fi
if [ $ENFORCEABLE -eq 0 ]; then
    echo "[memguard] 이 호스트는 user cgroup memory 위임이 없어 한도 강제가 불가합니다." >&2
    echo "[memguard] 관리자 조치 필요: /etc/systemd/system/user@.service.d/delegate.conf 에" >&2
    echo "           [Service] Delegate=memory pids 추가 후 systemctl daemon-reload" >&2
    if [ $ALLOW_UNENFORCED -eq 1 ]; then
        echo "[memguard] --allow-unenforced: 한도 없이 그대로 실행합니다 (preflight만 통과한 상태)" >&2
        exec "$@"
    fi
    exit 77
fi

UNIT_ARG=()
[ -n "$NAME" ] && UNIT_ARG=(--unit "memguard-${NAME}-$$")
SWAP_ARG=()
[ -n "$SWAP_PROP" ] && SWAP_ARG=(-p "MemorySwapMax=$SWAP_PROP")
printf '%s [run] high=%s max=%s swapmax=%s cmd=%s\n' "$(date '+%F %T')" "$HIGH" "$MAX" "${SWAP_PROP:-none}" "$*" >> "$LOG" 2>/dev/null || true

# 자가 정리 감시 서브셸 (헤더 2b). exec 전에 띄우므로 scope 밖에 남고, exec 뒤에도 PID 불변식($$ = 학습 PID)은 그대로다.
# 기다리는 대상은 이 스크립트의 PID·starttime(필드 22, comm 의 괄호 뒤로 자른다)이며 좀비도 «사라짐» 으로 본다.
if [ "${MEMGUARD_SELF_STOP:-1}" != "0" ] && [ -n "$NAME" ]; then
    SS_UNIT="memguard-${NAME}-$$.scope"; SS_PID=$$; SS_POLL="${MEMGUARD_STOP_POLL:-5}"
    ss_stat() {  # $1=PID → "상태 starttime"(없으면 빈 값)
        local s f
        s=$(< "/proc/$1/stat") 2>/dev/null || return 0
        read -r -a f <<< "${s##*) }"
        echo "${f[0]} ${f[19]}"
    }
    SS_START=$(ss_stat "$SS_PID"); SS_START="${SS_START#* }"
    (
        trap '' HUP INT QUIT
        while :; do
            read -r st sstart <<< "$(ss_stat "$SS_PID")"
            { [ -z "${st:-}" ] || [ "$st" = Z ] || [ "$sstart" != "$SS_START" ]; } && break
            sleep "$SS_POLL"
        done
        while :; do
            sd=$(find "$CG_ROOT" -type d -name "$SS_UNIT" -prune -print -quit 2>/dev/null)
            [ -z "$sd" ] && exit 0
            [ "$(scope_nprocs "$sd")" -eq 0 ] && break
            sleep "$SS_POLL"
        done
        systemctl --user stop "$SS_UNIT" >/dev/null 2>&1
    ) </dev/null >/dev/null 2>&1 &
    disown
fi

# scope 안에서 실행 — 자식·손자 프로세스 전부 동일 cgroup 한도에 묶인다
# --collect (2026-09-28 실사고 발견): 실패(비정상 종료)한 scope는 systemd-run 기본값상 사용자가
# `systemctl reset-failed` 를 치기 전까지 failed 상태로 남는다(정상 종료는 원래도 자동 해제).
# 실측: Hydra 설정 오류로 7초 만에 죽은 시도 3건이 loaded failed failed 로 방치돼 있었다.
# --collect(=CollectMode=inactive-or-failed)를 주면 실패해도 scope 가 곧바로 걷힌다.
exec systemd-run --user --scope -q --collect "${UNIT_ARG[@]}" \
    -p "MemoryHigh=$HIGH" -p "MemoryMax=$MAX" "${SWAP_ARG[@]}" -- "$@"
