#!/usr/bin/env bash
# mem-watch.sh — 사용자 권한 메모리 감시 (OOM발 SSH 장애 후속, 2026-08-18)
#
# 기준 (env로 조정 가능):
#   MemAvailable < WARN_AVAIL_GB(64)  → WARN (로그만, ntfy 안 보냄)
#   MemAvailable < CRIT_AVAIL_GB(32)  → CRIT (🚨 ntfy)
#   Swap 사용률 → 경보 없음, MSG·로그에 숫자만 (2026-09-29 사용자 지시)
#   실제 OOM 종료 → oom-watch.py 가 사건마다 💀 알림(죽은 프로세스, 개별 한도 초과인지 전체 고갈인지).
#
# 알림: scripts/claude-notify.sh direct 경로(주제는 env-config 의 USER_NTFY_TOPIC, 마스킹·예산 장부 공용).
#       주제가 없으면 claude-notify 가 조용히 건너뛴다. ALERT_WEBHOOK_URL 은 더 쓰지 않는다. 실패해도 exit 0 (cron 안전).
# 중복 억제: 상태 파일에 (level, 마지막 알림 시각) 저장 —
#   CRIT 진입 즉시 1회 + CRIT 지속 시 REALERT_SEC(1800s)마다 1회 + CRIT 해제 시 ✅ 1회.
#
# 메모리 압력 (2026-10-12, intent/2026-10-12-host-memory-budget-and-pressure.md):
#   MemAvailable 이 넉넉해도 판 여럿이 각자 high 까지 자라면 systemd-oomd 가 사용자 서비스 전체의 압력(PSI)으로
#   scope 를 종료한다(10-12). 당시 압력 값이 기록된 곳이 없어 사후 확인이 안 됐다. 그래서
#   매분 사용자 서비스 cgroup 의 memory.pressure `full avg10`·`avg60` 을 MSG·로그에 `Pressure=<avg10>/<avg60>%` 로 남긴다
#   (못 읽으면 `Pressure=?`).
#   압력은 기록만 하고 알리지 않는다(2026-10-12 사용자 지시: 알림은 메모리로 발사가 거부됐을 때(memguard-run.sh)와
#   판이 강제 종료됐을 때(oom-watch 💀·train-watcher)만). full avg60 ≥ PRESSURE_LOG_PCT(기록 문턱, 기본 15, env)인 분에는
#   scope 별 full avg10 상위 5개(+memory.current)를 로그에 한 줄씩 남긴다(memguard- 접두·끝 pid 제외한 이름).
#   시험용 틈: MEMGUARD_TEST_ROOT=<폴더> 가 있으면 그 아래 cgroup/ 나무를 대신 읽는다(경고 줄을 표준에러에 낸다).
#
# 설치(자동 등록 안 함 — 보고서의 설치 명령 참조): cron 매분 실행 권장.
# REF: knowledge/harness/code-history/tools__mem-guard__mem-watch.sh.md

set -u

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="${MEMWATCH_LOG:-$DIR/mem-watch.log}"
STATE="${MEMWATCH_STATE:-$DIR/mem-watch.state}"
WARN_AVAIL_GB="${WARN_AVAIL_GB:-64}"
CRIT_AVAIL_GB="${CRIT_AVAIL_GB:-32}"
REALERT_SEC="${REALERT_SEC:-1800}"
PRESSURE_LOG_PCT="${PRESSURE_LOG_PCT:-15}"
CG_ROOT="/sys/fs/cgroup/user.slice/user-$(id -u).slice/user@$(id -u).service"
if [ -n "${MEMGUARD_TEST_ROOT:-}" ]; then
    CG_ROOT="$MEMGUARD_TEST_ROOT/cgroup"
    echo "[mem-watch] 경고: 시험용 경로 사용 중 (MEMGUARD_TEST_ROOT=$MEMGUARD_TEST_ROOT)" >&2
fi

NOW=$(date +%s)
TS=$(date '+%F %T')

AVAIL_KB=$(awk '/^MemAvailable:/{print $2}' /proc/meminfo)
SWAP_TOTAL=$(awk '/^SwapTotal:/{print $2}' /proc/meminfo)
SWAP_FREE=$(awk '/^SwapFree:/{print $2}' /proc/meminfo)
AVAIL_GB=$(( AVAIL_KB / 1048576 ))
SWAP_PCT=0
[ "$SWAP_TOTAL" -gt 0 ] && SWAP_PCT=$(( (SWAP_TOTAL - SWAP_FREE) * 100 / SWAP_TOTAL ))

LEVEL="OK"; REASONS=""
if [ "$AVAIL_GB" -lt "$CRIT_AVAIL_GB" ]; then
    LEVEL="CRIT"; REASONS="MemAvailable ${AVAIL_GB}GiB < ${CRIT_AVAIL_GB}GiB(심각)"
elif [ "$AVAIL_GB" -lt "$WARN_AVAIL_GB" ]; then
    LEVEL="WARN"; REASONS="MemAvailable ${AVAIL_GB}GiB < ${WARN_AVAIL_GB}GiB"
fi
# WHY: Swap 점유율은 경보 레벨을 올리지 않는다(2026-09-29 사용자 지시 «swap 경고는 ntfy 에서 빼라»).

# WHY: 직접 curl 대신 scripts/claude-notify.sh 의 direct 경로로 보내 같은 마스킹 · 일일 예산 장부 · 큐를
# 지나고, 알림 주제(URL)가 cron 환경변수 · curl 인자에 남지 않는다(2026-10-01 감사 D5).
NOTIFY="$DIR/../../scripts/claude-notify.sh"
# WHY: 표준입력을 비워야 scripts/claude-notify.sh 가 direct 로 판별한다.
send() {
    [ -f "$NOTIFY" ] || { echo "$TS [mem-watch] claude-notify.sh 없음 — 알림 생략" >> "$LOG" 2>/dev/null; return 0; }
    bash "$NOTIFY" "mem-watch" "$1" </dev/null >/dev/null 2>&1 || true
}

read_full_psi() {
    awk '$1=="full"{for(i=2;i<=NF;i++){split($i,a,"=");if(a[1]=="avg10")x=a[2];if(a[1]=="avg60")y=a[2]}} END{if(x!=""&&y!="")print x, y}' "$1" 2>/dev/null
}
P10=""; P60=""
read -r P10 P60 < <(read_full_psi "$CG_ROOT/memory.pressure") || true
case "$P10$P60" in ''|*[!0-9.]*) P10=""; P60="" ;; esac
PRESS_TXT="?"; [ -n "$P60" ] && PRESS_TXT="${P10}/${P60}%"

EMOJI=""
[ "$LEVEL" = "CRIT" ] && EMOJI="🚨 "
MSG="${EMOJI}[mem-watch $(hostname)] $LEVEL: MemAvailable=${AVAIL_GB}GiB Swap=${SWAP_PCT}% Pressure=${PRESS_TXT}${REASONS:+ — $REASONS}"

LAST_LEVEL="OK"; LAST_ALERT=0
[ -f "$STATE" ] && read -r LAST_LEVEL LAST_ALERT < "$STATE" 2>/dev/null || true
case "$LAST_ALERT" in *[!0-9]*|"") LAST_ALERT=0 ;; esac

SEND=0
if [ "$LEVEL" = "CRIT" ]; then
    if [ "$LAST_LEVEL" != "CRIT" ] || [ $(( NOW - LAST_ALERT )) -ge "$REALERT_SEC" ]; then SEND=1; fi
elif [ "$LAST_LEVEL" = "CRIT" ]; then
    SEND=1; MSG="✅ [mem-watch $(hostname)] CRIT 해제 → $LEVEL: MemAvailable=${AVAIL_GB}GiB Swap=${SWAP_PCT}% Pressure=${PRESS_TXT}"
fi

echo "$TS $MSG$([ $SEND -eq 1 ] && echo ' [alert]')" >> "$LOG" 2>/dev/null || true

if [ $SEND -eq 1 ]; then
    send "$MSG"
    echo "$LEVEL $NOW" > "$STATE" 2>/dev/null || true
else
    echo "$LEVEL $LAST_ALERT" > "$STATE" 2>/dev/null || true
fi

short_scope() {
    local s="${1#memguard-}"; s="${s%.scope}"; echo "${s%-[0-9]*}"
}
top_scopes() {
    local sc a cu
    while IFS= read -r -d '' sc; do
        a=$(read_full_psi "$sc/memory.pressure" | awk '{print $1}'); cu=""
        { read -r cu < "$sc/memory.current"; } 2>/dev/null || true
        case "$cu" in ''|*[!0-9]*) cu=0 ;; esac
        echo "${a:-0} $(( cu / 1073741824 )) $(short_scope "$(basename "$sc")")"
    done < <(find "$CG_ROOT" -type d -name 'memguard-*.scope' -prune -print0 2>/dev/null) | LC_ALL=C sort -k1,1nr -k2,2nr | head -n 5
}
if [ -n "$P60" ] && awk -v p="$P60" -v t="$PRESSURE_LOG_PCT" 'BEGIN{exit !(p+0>=t+0)}'; then
    N=0
    while IFS= read -r L; do
        [ -n "$L" ] || continue
        N=$(( N + 1 ))
        read -r T_A T_C T_N <<< "$L"
        echo "$TS [mem-watch] 압력 상위 ${N}: ${T_N} full avg10=${T_A}% current=${T_C}GiB" >> "$LOG" 2>/dev/null || true
    done <<< "$(top_scopes)"
fi

while IFS= read -r KILL_MSG; do
    [ -n "$KILL_MSG" ] || continue
    echo "$TS $KILL_MSG [alert]" >> "$LOG" 2>/dev/null || true
    send "$KILL_MSG"
done < <(timeout 40 python3 "$DIR/oom-watch.py" 2>>"$LOG")

LINES=$(wc -l < "$LOG" 2>/dev/null || echo 0)
if [ "$LINES" -gt 10000 ]; then
    TMP="$LOG.tmp.$$"
    if ! { tail -n 4000 "$LOG" > "$TMP" 2>/dev/null && mv "$TMP" "$LOG" 2>/dev/null; }; then rm -f "$TMP" 2>/dev/null; fi
fi
exit 0
