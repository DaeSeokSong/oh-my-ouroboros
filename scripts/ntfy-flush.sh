#!/bin/bash
# =============================================================
# ntfy 큐 독립 배송기 — cron 이 매분 부른다. 세션과 무관하게 큐를 비운다.
#
# 동작:
#   · 예산·halt·선증가·우선순위·재시도는 새로 만들지 않고 claude-notify.sh 를
#     CLAUDE_NOTIFY_FLUSH_ONLY=1 로 불러 그대로 탄다(한 번에 큐 한 건).
#   · 한 실행에 최대 NTFY_FLUSH_MAX(기본 10)건. 큐 줄 수가 줄지 않으면(실패·예산 소진·
#     중단) 그 자리에서 멈춘다. 건 사이 1초 쉼. 42초 넘으면 새 건을 시작하지 않는다.
#     한 건은 최대 15초(timeout)라 최악 약 58초까지 걸려 다음 분과 겹칠 수 있으나
#     ntfy-flush.lock(flock -n)이 겹침을 막는다. 발송 성공 여부는 발송 로그의 flush_sent 증가로 판정한다.
#   · 진행 없이 멈추거나 호출이 timeout(124·137)으로 끊기면 ntfy-flush.backoff 를 갱신하고,
#     그 수정 시각이 NTFY_FLUSH_BACKOFF_SEC(기본 300)초 이내면 아무것도 안 하고 끝난다.
#     한 건이라도 보내면 파일을 지운다. 배송 전용 모드는 재시도 가능한 실패(429·000·5xx)에
#     tries 를 올리지 않고 원래 적재 시각으로 되돌리므로, 짧은 장애에 줄이 버려지지 않는다.
#   · ntfy-flush.lock 으로 겹쳐 돌지 않는다. 표준출력·표준에러는 비우고 항상 0 으로 끝난다.
#   · 토픽·URL 은 claude-notify.sh 가 env-config 에서 읽는다. 여기서 적거나 남기지 않는다.
#
# cron 등록 예시(crontab -e):
#   * * * * * ~/.claude/scripts/ntfy-flush.sh
# REF: knowledge/harness/code-history/scripts__ntfy-flush.sh.md
# =============================================================

exec >/dev/null 2>&1
cd / || exit 0

[ -n "${HOME:-}" ] || exit 0
NOTIFY="$(cd "$(dirname "$0")" && pwd)/claude-notify.sh"
USAGE_DIR="$HOME/.claude/_usage"
QUEUE_FILE="$USAGE_DIR/ntfy-queue.tsv"

DAY="${NTFY_DAY:-$(date -u +%Y%m%d)}"
[[ "$DAY" =~ ^[0-9]{8}$ ]] || DAY=$(date -u +%Y%m%d)
MAX="${NTFY_FLUSH_MAX:-10}"
[[ "$MAX" =~ ^[0-9]{1,3}$ ]] || MAX=10
MAX=$((10#$MAX))

SEND_LOG="$HOME/.claude/_audit/ntfy-send.tsv"

# WHY: 잠금 실패분(.spill)도 센다. 빼면 큐가 비어 보여 배송이 멈춘다(scripts/claude-notify.sh 가 잠금 안에서 합친다).
queue_count() {
    local n=0 m=0
    [ -f "$QUEUE_FILE" ] && n=$(grep -c . "$QUEUE_FILE" 2>/dev/null)
    [ -f "$QUEUE_FILE.spill" ] && m=$(grep -c . "$QUEUE_FILE.spill" 2>/dev/null)
    echo $(( ${n:-0} + ${m:-0} ))
}

# WHY: 줄 수 감소만으로는 4xx 폐기·무효 줄 정리도 «발송»으로 잡혀 backoff 가 거짓으로 풀린다(2026-10-01 감사 D6).
sent_count() {
    local n=0
    [ -f "$SEND_LOG" ] && n=$(grep -c -P '\tflush_sent$' "$SEND_LOG" 2>/dev/null)
    echo "${n:-0}"
}

# WHY: scripts/claude-notify.sh 의 halt_active 와 같은 판정이다(새 공용 파일을 만들지 않으려고 두 스크립트에 같은 몇 줄을 둔다).
halt_active() {
    local f="$USAGE_DIR/ntfy-$DAY.halt" sec="${NTFY_HALT_RETRY_SEC:-3600}" age
    [ -f "$f" ] || return 1
    [[ "$sec" =~ ^[0-9]{1,6}$ ]] || sec=3600
    sec=$((10#$sec))
    [ "$sec" -eq 0 ] && return 0
    age=$(( $(date +%s) - $(stat -c %Y "$f" 2>/dev/null || echo 0) ))
    [ "$age" -lt "$sec" ]
}

[ "$(queue_count)" -gt 0 ] || exit 0
halt_active && exit 0

BACKOFF_FILE="$USAGE_DIR/ntfy-flush.backoff"
BACKOFF_SEC="${NTFY_FLUSH_BACKOFF_SEC:-300}"
[[ "$BACKOFF_SEC" =~ ^[0-9]{1,5}$ ]] || BACKOFF_SEC=300
BACKOFF_SEC=$((10#$BACKOFF_SEC))
if [ "$BACKOFF_SEC" -gt 0 ] && [ -f "$BACKOFF_FILE" ]; then
    age=$(( $(date +%s) - $(stat -c %Y "$BACKOFF_FILE" 2>/dev/null || echo 0) ))
    [ "$age" -ge "$BACKOFF_SEC" ] || exit 0
fi

{ exec 8>"$USAGE_DIR/ntfy-flush.lock"; } 2>/dev/null || exit 0
flock -n 8 || exit 0

sent=0
while [ "$sent" -lt "$MAX" ] && [ "$SECONDS" -lt 42 ]; do
    before=$(queue_count)
    sent_before=$(sent_count)
    [ "$before" -gt 0 ] || break
    halt_active && break
    CLAUDE_NOTIFY_FLUSH_ONLY=1 timeout 15 bash "$NOTIFY" </dev/null
    rc=$?
    after=$(queue_count)
    # WHY: timeout(124)·SIGKILL(137)로 끊긴 호출은 보냈는지 알 수 없어 줄 수와 무관하게 실패로 본다.
    if [ "$rc" -eq 124 ] || [ "$rc" -eq 137 ] || [ "$after" -ge "$before" ]; then
        : > "$BACKOFF_FILE" 2>/dev/null
        break
    fi
    if [ "$(sent_count)" -gt "$sent_before" ]; then
        rm -f "$BACKOFF_FILE" 2>/dev/null
    fi
    sent=$((sent + 1))
    sleep 1
done
exit 0
