#!/bin/bash
# =============================================================
# Claude Code Notification Script v1.1
# - Phone + PC push notification (ntfy.sh)
# - Terminal bell (SSH 환경에서도 동작)
# - Desktop notification (DISPLAY 있을 때만)
#
# 42908 중단(halt)은 «유효 시간이 있는 중단» 이다: halt 파일의
#   수정 시각이 NTFY_HALT_RETRY_SEC(기본 3600) 초를 넘으면 중단이 풀린 것으로 보고 한 건만 시험한다
#   (한 시간에 한 건). 다시 42908 이면 halt 를 갱신, 2xx 면 halt 를 지운다. 0 이면 종전(하루 통째).
# REF: knowledge/harness/code-history/scripts__claude-notify.sh.md
# =============================================================

# WHY: claudenews 플러그인이 한 주기마다 띄우는 `claude --print` 자식들도 사용자 전역 Stop 훅을 그대로 물려받아
# 주기마다 알림이 4~5건씩 몰렸다(2026-09-11 사용자 지시). 플러그인은 `--settings` 로 «플러그인만» 끄므로 사용자 훅은 살아남는다. 따라서 여기서 막는다.
#   · CODE_EARN_BACKGROUND_CHILD — 플러그인이 자식 env 에 직접 넣는 표식(1차 판별)
#   · CLAUDE_NOTIFY_SKIP        — 다른 자동화가 알림을 끄고 싶을 때 쓰는 손잡이
#   · cwd 가 ~/.claudenews      — env 상속이 끊겨도 걸리는 2차 그물
[ -n "${CODE_EARN_BACKGROUND_CHILD:-}" ] && exit 0
[ -n "${CLAUDE_NOTIFY_SKIP:-}" ] && exit 0
[ "$(pwd -P 2>/dev/null)" = "$(cd "${HOME}/.claudenews" 2>/dev/null && pwd -P)" ] && exit 0

CLAUDE_HOME="${CLAUDE_HOME:-${HOME}/.claude}"
for _cfg in "${CLAUDE_HOME}/env-config" "${CLAUDE_HOME}/config/env-config"; do
    # shellcheck source=/dev/null
    [ -f "$_cfg" ] && source "$_cfg"
done
unset _cfg

NTFY_TOPIC="${USER_NTFY_TOPIC:-}"
NTFY_SERVER="${NTFY_SERVER:-https://ntfy.sh}"
SERVER="$(hostname -s)"

# WHY: 공개 서버(ntfy.sh)로 나가는 글이므로 직접 호출(와쳐·mem-watch·온톨로지)·큐·재발송 어느 경로든
# 같은 함수를 지나야 한다(2026-10-01 감사 D5: 표지 줄 경로에만 있던 마스킹을 모든 경로로).
# 대상은 rules-lazy/secret-management.md §1·config/public-export-rules.txt 의 토큰 형태 + 긴 점 구분
# 숫자열(DICOM UID 형태, 환자 식별자 유출 방지). 접두형은 앞 글자가 영숫자면 단어 일부(task-…)라 건너뛴다.
MASK_SED=(
    -e 's/(^|[^A-Za-z0-9])(sk|tvly)-[A-Za-z0-9_-]{8,}/\1<masked>/g'
    -e 's/(^|[^A-Za-z0-9])m0-[A-Za-z0-9]{16,}/\1<masked>/g'
    -e 's/AKIA[A-Z0-9]{12,}/<masked>/g'
    -e 's/AIza[0-9A-Za-z_-]{30,}/<masked>/g'
    -e 's/gh[pousr]_[A-Za-z0-9]{20,}/<masked>/g'
    -e 's/github_pat_[A-Za-z0-9_]{16,}/<masked>/g'
    -e 's/xox[abprs]-[A-Za-z0-9-]{8,}/<masked>/g'
    -e 's/AT(ATT|BB|CTT)[A-Za-z0-9_=-]{16,}/<masked>/g'
    -e 's/Bearer [A-Za-z0-9._-]{16,}/<masked>/g'
    -e 's/ntfy\.sh\/[A-Za-z0-9_-]+/ntfy.sh\/<masked>/g'
    -e 's/[0-9a-fA-F]{32,}/<masked>/g'
    -e 's/[0-9]+(\.[0-9]+){5,}/<masked>/g'
)
sanitize_text() {  # WHY: 200 코드포인트 절단은 jq 슬라이스로 한다(한글이 깨지지 않는다)
    printf '%s' "$1" | tr -d '\n\t\r\033' | sed -E "${MASK_SED[@]}" | jq -Rr '.[0:200]' 2>/dev/null
}
curl_cfg_escape() {
    local s="${1//\\/\\\\}"
    printf '%s' "${s//\"/\\\"}"
}

PROJECT="${1:-Claude}"
SUMMARY="${2:-작업 완료}"
TITLE="[$SERVER: $PROJECT]"
MSG="$SUMMARY"
TAG="white_check_mark"
PRIORITY="default"
KIND="routine"
SKIP_CURRENT=0

# WHY: 잡 세션(CLAUDE_JOB_DIR)의 Stop 이벤트에서만 표지 줄(result:/needs input:/failed:) 유무로 알림을 거른다(사용자 결정 2026-09-26).
# 잡이 아닌 Stop에는 표지 게이트를 적용하지 않는다.
# REF: intent/2026-09-26-ntfy-final-only.md
INPUT=""
# WHY: 큐 배송 전용(2026-10-01, scripts/ntfy-flush.sh 가 cron 에서 호출): 표준입력을 읽지 않고
# 현재 알림 없이 큐 한 건만 보낸다. 벨·데스크톱 알림은 아래 SKIP 종료로 건너뛴다.
if [ -n "${CLAUDE_NOTIFY_FLUSH_ONLY:-}" ]; then
    SKIP_CURRENT=1
elif [ ! -t 0 ]; then
    INPUT=$(timeout 2 cat 2>/dev/null)
fi

HOOK_EVENT=""
if [ -n "$INPUT" ]; then
    HOOK_EVENT=$(printf '%s' "$INPUT" | jq -r '.hook_event_name // empty' 2>/dev/null)
fi
if [ -z "$HOOK_EVENT" ]; then
    KIND="direct"
fi
if [ "$SUMMARY" = "권한 승인 필요" ] || [ "$HOOK_EVENT" = "Notification" ]; then
    KIND="permission"
fi

if [ -n "${CLAUDE_JOB_DIR:-}" ] && [ -n "$INPUT" ]; then
    if [ "$HOOK_EVENT" = "Stop" ]; then
        KIND="failopen"
        TRANSCRIPT=$(printf '%s' "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null)
        # WHY: Stop 입력의 last_assistant_message 를 먼저 쓴다(2026-10-16). Stop 시점에 마지막 text 줄이
        # transcript 에 아직 flush 되지 않는 경합으로 표지 알림이 조용히 SKIP 되던 문제 때문이다.
        LAST_TEXT=$(printf '%s' "$INPUT" | jq -r '.last_assistant_message // empty' 2>/dev/null)
        if [ -n "$LAST_TEXT" ] || { [ -n "$TRANSCRIPT" ] && [ -f "$TRANSCRIPT" ]; }; then
            # shellcheck disable=SC2016  # jq 식의 $ 는 셸이 아니라 jq 가 해석한다
            JQ_FILTER='
              [ .[] | select(.type=="assistant") ] | last
              | .message.content? as $c
              | if ($c|type) == "array" then
                  ( $c[] | select(.type=="text") | .text )
                elif ($c|type) == "string" then
                  $c
                else empty end
            '
            if [ -n "$LAST_TEXT" ]; then
                EXTRACT_RC=0
            else
                # shellcheck disable=SC2016  # bash -c 안의 $1 $2 는 자식 셸이 해석한다
                LAST_TEXT=$(timeout 4 bash -c 'tail -n 1000 "$1" 2>/dev/null | jq -rs "$2" 2>/dev/null' _ "$TRANSCRIPT" "$JQ_FILTER")
                EXTRACT_RC=$?
            fi
            if [ "$EXTRACT_RC" -eq 0 ]; then
                if [ -z "$LAST_TEXT" ]; then
                    [ -n "${CLAUDE_NOTIFY_DRYRUN:-}" ] && printf 'SKIP\n' && exit 0
                    SKIP_CURRENT=1
                else
                    # WHY: 표지는 소문자만 본다(대문자 RESULT:는 에이전트 T41 계약이라 다른 규약).
                    MARK_LINE=$(printf '%s\n' "$LAST_TEXT" | awk '
                      BEGIN { infence = 0 }
                      {
                        line = $0
                        s = line
                        sub(/^[[:space:]]+/, "", s)
                        if (s ~ /^```/) { infence = !infence; next }
                        if (infence) next
                        if (s ~ /^>/) next
                        if (s ~ /^failed:/) { f = line }
                        else if (s ~ /^needs input:/) { n = line }
                        else if (s ~ /^result:/) { r = line }
                      }
                      END {
                        if (f != "") { print f; exit }
                        if (n != "") { print n; exit }
                        if (r != "") { print r; exit }
                      }
                    ')
                    if [ -z "$MARK_LINE" ]; then
                        [ -n "${CLAUDE_NOTIFY_DRYRUN:-}" ] && printf 'SKIP\n' && exit 0
                        SKIP_CURRENT=1
                    else
                        STRIPPED_MARK=$(printf '%s' "$MARK_LINE" | sed -E 's/^[[:space:]]+//')
                        case "$STRIPPED_MARK" in
                            needs\ input:*) KIND="needs_input"; TAG="question"; PRIORITY="high" ;;
                            failed:*)       KIND="failed"; TAG="x" ;;
                            result:*)       KIND="final"; TAG="white_check_mark" ;;
                        esac
                        # WHY: 200은 ntfy 미리보기 한 줄 기준의 임의값. tail 1000은 관측된
                        # assistant 아닌 연속 줄 최대 66 대비 여유값.
                        MSG="$STRIPPED_MARK"
                    fi
                fi
            fi
        fi
    fi
fi

MSG=$(sanitize_text "$MSG")

if [ -n "${CLAUDE_NOTIFY_DRYRUN:-}" ]; then
    printf 'NOTIFY\t%s\t%s\t%s\n' "$PRIORITY" "$TAG" "$MSG"
    exit 0
fi

if [ -n "$NTFY_TOPIC" ] && command -v curl >/dev/null 2>&1; then
    umask 077
    TITLE=$(printf '%s' "$TITLE" | tr -d '\n\t\r\033')
    USAGE_DIR="$HOME/.claude/_usage"
    AUDIT_DIR="$HOME/.claude/_audit"
    if mkdir -p "$USAGE_DIR" "$AUDIT_DIR" 2>/dev/null; then
        find "$USAGE_DIR" -maxdepth 1 -type f \
            \( -name 'ntfy-*.count' -o -name 'ntfy-*.halt' -o -name 'ntfy-*.failopen' \) \
            -mtime +7 -delete 2>/dev/null || :
        DAY="${NTFY_DAY:-$(date -u +%Y%m%d 2>/dev/null)}"
        [[ "$DAY" =~ ^[0-9]{8}$ ]] || DAY=$(date -u +%Y%m%d 2>/dev/null)
        CAP_RAW="${NTFY_DAILY_CAP:-200}"
        if [[ "$CAP_RAW" =~ ^[0-9]+$ ]] && [ "${#CAP_RAW}" -le 4 ] &&
           [ "$((10#$CAP_RAW))" -le 250 ]; then
            CAP=$((10#$CAP_RAW))
        else
            CAP=200
        fi
        RESERVE_RAW="${NTFY_RESERVE:-40}"
        if [[ "$RESERVE_RAW" =~ ^[0-9]+$ ]] && [ "${#RESERVE_RAW}" -le 4 ] &&
           [ "$((10#$RESERVE_RAW))" -le "$CAP" ]; then
            RESERVE=$((10#$RESERVE_RAW))
        else
            RESERVE=40
            [ "$RESERVE" -gt "$CAP" ] && RESERVE="$CAP"
        fi
        NORMAL_LIMIT=$((CAP - RESERVE))
        COUNT_FILE="$USAGE_DIR/ntfy-$DAY.count"
        HALT_FILE="$USAGE_DIR/ntfy-$DAY.halt"
        FAILOPEN_FILE="$USAGE_DIR/ntfy-$DAY.failopen"
        halt_active() {
            [ -f "$HALT_FILE" ] || return 1
            local sec="${NTFY_HALT_RETRY_SEC:-3600}" age
            [[ "$sec" =~ ^[0-9]{1,6}$ ]] || sec=3600
            sec=$((10#$sec))
            [ "$sec" -eq 0 ] && return 0
            age=$(( $(date +%s) - $(stat -c %Y "$HALT_FILE" 2>/dev/null || echo 0) ))
            [ "$age" -lt "$sec" ]
        }
        CAP_FILE="$USAGE_DIR/ntfy-cap"
        QUEUE_FILE="$USAGE_DIR/ntfy-queue.tsv"
        LOG_FILE="$AUDIT_DIR/ntfy-send.tsv"
        LOCK_FILE="$USAGE_DIR/ntfy-budget.lock"

        SESSION="-"
        if [ -n "$INPUT" ]; then
            SESSION_RAW=$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)
            SESSION=$(jq -rn --arg s "$SESSION_RAW" '$s | gsub("[^A-Za-z0-9_-]"; "") | .[0:64]' 2>/dev/null)
            [ -n "$SESSION" ] || SESSION="-"
        fi

        log_send() {
            printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
                "$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)" \
                "${5:-$SESSION}" "$1" "$2" "$3" "$4" >> "$LOG_FILE" 2>/dev/null || :
        }

        queue_text() { sanitize_text "$1"; }

        parse_queue_line() {
            local rest="$1" i
            local fields=()
            for ((i = 0; i < 7; i++)); do
                [[ "$rest" == *$'\t'* ]] || return 1
                fields+=("${rest%%$'\t'*}")
                rest="${rest#*$'\t'}"
            done
            [[ "$rest" != *$'\t'* ]] || return 1
            fields+=("$rest")
            case "${fields[2]}" in
                permission|needs_input|failed|final|direct) ;;
                *) return 1 ;;
            esac
            Q_TS="${fields[0]}"
            Q_SESSION="${fields[1]}"
            Q_KIND="${fields[2]}"
            Q_PRIORITY="${fields[3]}"
            Q_TAG="${fields[4]}"
            Q_TITLE="${fields[5]}"
            Q_MSG="${fields[6]}"
            Q_TRIES="${fields[7]}"
        }

        LOCK_OPEN=1
        { exec 9>"$LOCK_FILE"; } 2>/dev/null || LOCK_OPEN=0
        lock_budget() {
            [ "$LOCK_OPEN" -eq 1 ] && flock -w 1 9 >/dev/null 2>&1
        }
        unlock_budget() {
            flock -u 9 >/dev/null 2>&1 || :
        }
        read_number() {
            NUMBER=0
            [ -f "$1" ] && read -r NUMBER < "$1"
            [[ "$NUMBER" =~ ^[0-9]+$ ]] || NUMBER=0
            [ "${#NUMBER}" -le 9 ] || NUMBER=0
            NUMBER=$((10#$NUMBER))
        }
        # WHY: 잠금을 못 잡은 호출이 적은 줄(.spill)은 큐 전체를 교체하는 save_queue 에 덮이지 않도록 따로 두고,
        # 다음 잠금 보유자가 여기서 큐에 합친다(2026-10-01 감사 D4). load_queue 는 항상 잠금 안에서만 부른다.
        load_queue() {
            Q_LINES=()
            [ -f "$QUEUE_FILE" ] && mapfile -t Q_LINES < "$QUEUE_FILE"
            local q spill="$QUEUE_FILE.spill" taken="$QUEUE_FILE.spill.$$" spilled=()
            if [ -s "$spill" ] && mv -f "$spill" "$taken" 2>/dev/null; then
                mapfile -t spilled < "$taken"
                Q_LINES+=("${spilled[@]}")
                if save_queue; then
                    rm -f "$taken" 2>/dev/null || :
                else
                    cat "$taken" >> "$spill" 2>/dev/null && rm -f "$taken" 2>/dev/null
                fi
            fi
            for q in "${Q_LINES[@]}"; do
                if ! parse_queue_line "$q"; then
                    save_queue || :
                    break
                fi
            done
        }
        save_queue() {
            local temp q
            local valid=()
            local invalid=0
            temp=$(mktemp "$USAGE_DIR/.ntfy-queue.XXXXXX" 2>/dev/null) || return 1
            for q in "${Q_LINES[@]}"; do
                if parse_queue_line "$q"; then
                    valid+=("$q")
                else
                    invalid=$((invalid + 1))
                fi
            done
            if ! { for q in "${valid[@]}"; do printf '%s\n' "$q"; done; } > "$temp"; then
                rm -f "$temp" 2>/dev/null || :
                return 1
            fi
            if ! mv -f "$temp" "$QUEUE_FILE" 2>/dev/null; then
                rm -f "$temp" 2>/dev/null || :
                return 1
            fi
            Q_LINES=("${valid[@]}")
            while [ "$invalid" -gt 0 ]; do
                log_send "invalid" "-" 0 "queue_drop"
                invalid=$((invalid - 1))
            done
        }
        append_queue() {
            local qts qs qk qp qtag qt qm qtry line drop i oldest final_drop
            qs="$1"; qk="$2"; qp="$3"; qtag="$4"; qt="$5"; qm="$6"; qtry="$7"
            qts="${8:-$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)}"
            printf -v line '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s' \
                "$qts" "$qs" "$qk" "$qp" "$qtag" "$qt" "$qm" "$qtry"
            if [ "${UNLOCKED_APPEND:-0}" -eq 1 ]; then
                printf '%s\n' "$line" >> "$QUEUE_FILE.spill" 2>/dev/null
                return
            fi
            load_queue
            Q_LINES+=("$line")
            if [ "${#Q_LINES[@]}" -gt 30 ]; then
                drop=-1
                final_drop=-1
                oldest=""
                for i in "${!Q_LINES[@]}"; do
                    parse_queue_line "${Q_LINES[$i]}" || continue
                    if [ "$drop" -lt 0 ] || [[ "$Q_TS" < "$oldest" ]]; then
                        drop="$i"
                        oldest="$Q_TS"
                    fi
                    if [ "$Q_KIND" = "final" ]; then
                        if [ "$final_drop" -lt 0 ] ||
                           [[ "$Q_TS" < "$final_oldest" ]]; then
                            final_drop="$i"
                            final_oldest="$Q_TS"
                        fi
                    fi
                done
                [ "$final_drop" -ge 0 ] && drop="$final_drop"
                parse_queue_line "${Q_LINES[$drop]}"
                local dropped_kind="$Q_KIND" dropped_session="$Q_SESSION"
                unset 'Q_LINES[drop]'
                Q_LINES=("${Q_LINES[@]}")
                log_send "$dropped_kind" "-" 0 "queue_drop" "$dropped_session"
            fi
            save_queue
        }
        select_queue() {
            local i rank best_rank best_ts=""
            SELECTED=-1
            best_rank=99
            for i in "${!Q_LINES[@]}"; do
                parse_queue_line "${Q_LINES[$i]}" || continue
                case "$Q_KIND" in
                    permission) rank=0 ;;
                    needs_input) rank=1 ;;
                    failed) rank=2 ;;
                    final|direct) rank=3 ;;
                esac
                if [ "$rank" -lt "$best_rank" ] ||
                   { [ "$rank" -eq "$best_rank" ] &&
                     [[ "$Q_TS" < "$best_ts" ]]; }; then
                    best_rank="$rank"
                    best_ts="$Q_TS"
                    SELECTED="$i"
                fi
            done
        }

        TO_SEND=0
        FROM_QUEUE=0
        RESERVED=0
        LOCK_SEND=0
        UNLOCKED_APPEND=0
        SEND_KIND="$KIND"
        SEND_MSG="$MSG"
        SEND_TITLE="$TITLE"
        SEND_TAG="$TAG"
        SEND_PRIORITY="$PRIORITY"
        SEND_SESSION="$SESSION"
        SEND_TRIES=0
        SEND_TS=""
        HALT_TRIAL=0
        if lock_budget; then
            printf '%s\n' "$CAP" > "$CAP_FILE" 2>/dev/null || :
            read_number "$COUNT_FILE"; COUNT="$NUMBER"
            read_number "$FAILOPEN_FILE"; FAILOPEN_COUNT="$NUMBER"
            load_queue
            Q_COUNT=0
            for q in "${Q_LINES[@]}"; do
                parse_queue_line "$q" && Q_COUNT=$((Q_COUNT + 1))
            done
            HALTED=0
            halt_active && HALTED=1
            [ "$HALTED" -eq 0 ] && [ -f "$HALT_FILE" ] && HALT_TRIAL=1

            if [ "$CAP" -eq 0 ]; then
                if [ "$HALTED" -eq 0 ] && [ "$SKIP_CURRENT" -eq 0 ] &&
                   [ "$SECONDS" -lt 8 ]; then
                    TO_SEND=1
                elif [ "$SKIP_CURRENT" -eq 0 ]; then
                    if [ "$HALTED" -eq 1 ]; then
                        log_send "$KIND" "-" 0 "halt_skip"
                    else
                        log_send "$KIND" "-" 0 "send_fail"
                    fi
                fi
            elif [ "$HALTED" -eq 1 ]; then
                if [ "$SKIP_CURRENT" -eq 0 ]; then
                    case "$KIND" in
                        final|needs_input|failed|permission|direct)
                            Q_MSG=$(queue_text "$MSG")
                            Q_TITLE=$(queue_text "$TITLE")
                            if append_queue "$SESSION" "$KIND" "$PRIORITY" "$TAG" "$Q_TITLE" "$Q_MSG" 0; then
                                log_send "$KIND" "-" 0 "queued"
                            fi
                            ;;
                        *) log_send "$KIND" "-" 0 "halt_skip" ;;
                    esac
                fi
            else
                if [ "$SKIP_CURRENT" -eq 0 ] && [ "$COUNT" -lt "$CAP" ] &&
                   [ "$SECONDS" -lt 8 ]; then
                    if [ "$KIND" = "permission" ]; then
                        TO_SEND=1
                    elif { [ "$KIND" = "final" ] || [ "$KIND" = "needs_input" ] ||
                           [ "$KIND" = "failed" ] || [ "$KIND" = "direct" ]; } &&
                         [ "$Q_COUNT" -eq 0 ]; then
                        TO_SEND=1
                    fi
                fi

                if [ "$TO_SEND" -eq 0 ] && [ "$Q_COUNT" -gt 0 ] &&
                   [ "$COUNT" -lt "$CAP" ] && [ "$SECONDS" -le 6 ]; then
                    select_queue
                    if [ "$SELECTED" -ge 0 ]; then
                        parse_queue_line "${Q_LINES[$SELECTED]}"
                        SEND_TS="$Q_TS"
                        SEND_SESSION="$Q_SESSION"
                        SEND_KIND="$Q_KIND"
                        SEND_PRIORITY="$Q_PRIORITY"
                        SEND_TAG="$Q_TAG"
                        SEND_TITLE="$Q_TITLE"
                        SEND_MSG="$Q_MSG"
                        SEND_TRIES="$Q_TRIES"
                        unset 'Q_LINES[SELECTED]'
                        Q_LINES=("${Q_LINES[@]}")
                        if save_queue; then
                            TO_SEND=1
                            FROM_QUEUE=1
                        fi
                    fi
                fi

                if [ "$TO_SEND" -eq 0 ] && [ "$SKIP_CURRENT" -eq 0 ] &&
                   [ "$Q_COUNT" -eq 0 ] && [ "$SECONDS" -lt 8 ]; then
                    if [ "$KIND" = "routine" ] && [ "$COUNT" -lt "$NORMAL_LIMIT" ]; then
                        TO_SEND=1
                    elif [ "$KIND" = "failopen" ] && [ "$COUNT" -lt "$CAP" ] &&
                         [ "$FAILOPEN_COUNT" -lt 5 ]; then
                        if printf '%s\n' "$((FAILOPEN_COUNT + 1))" > "$FAILOPEN_FILE" 2>/dev/null; then
                            TO_SEND=1
                        fi
                    fi
                fi

                if [ "$TO_SEND" -eq 1 ]; then
                    if printf '%s\n' "$((COUNT + 1))" > "$COUNT_FILE" 2>/dev/null; then
                        RESERVED=1
                    else
                        TO_SEND=0
                        if [ "$FROM_QUEUE" -eq 1 ]; then
                            append_queue "$SEND_SESSION" "$SEND_KIND" "$SEND_PRIORITY" \
                                "$SEND_TAG" "$SEND_TITLE" "$SEND_MSG" "$SEND_TRIES" "$SEND_TS" || :
                            FROM_QUEUE=0
                        fi
                    fi
                fi

                if [ "$SKIP_CURRENT" -eq 0 ] && [ "$TO_SEND" -eq 0 ]; then
                    case "$KIND" in
                        final|needs_input|failed|permission|direct)
                            Q_MSG=$(queue_text "$MSG")
                            Q_TITLE=$(queue_text "$TITLE")
                            if append_queue "$SESSION" "$KIND" "$PRIORITY" "$TAG" "$Q_TITLE" "$Q_MSG" 0; then
                                log_send "$KIND" "-" 0 "queued"
                            fi
                            ;;
                        *)
                            if [ "$COUNT" -ge "$NORMAL_LIMIT" ] ||
                               { [ "$KIND" = "failopen" ] &&
                                 { [ "$COUNT" -ge "$CAP" ] ||
                                   [ "$FAILOPEN_COUNT" -ge 5 ]; }; }; then
                                log_send "$KIND" "-" 0 "budget_skip"
                            elif [ "$FROM_QUEUE" -eq 0 ]; then
                                log_send "$KIND" "-" 0 "queue_defer"
                            fi
                            ;;
                    esac
                elif [ "$FROM_QUEUE" -eq 1 ] && [ "$SKIP_CURRENT" -eq 0 ]; then
                    case "$KIND" in
                        final|needs_input|failed|direct)
                            Q_MSG=$(queue_text "$MSG")
                            Q_TITLE=$(queue_text "$TITLE")
                            if append_queue "$SESSION" "$KIND" "$PRIORITY" "$TAG" "$Q_TITLE" "$Q_MSG" 0; then
                                log_send "$KIND" "-" 0 "queued"
                            fi
                            ;;
                        *)
                            log_send "$KIND" "-" 0 "queue_defer"
                            ;;
                    esac
                fi
            fi
            [ "$HALT_TRIAL" -eq 1 ] && [ "$TO_SEND" -eq 1 ] && { : > "$HALT_FILE" 2>/dev/null || :; }
            [ "$TO_SEND" -eq 1 ] || HALT_TRIAL=0
            unlock_budget
        else
            if [ -f "$HALT_FILE" ]; then
                if [ "$SKIP_CURRENT" -eq 0 ]; then
                    case "$KIND" in
                        final|needs_input|failed|permission|direct)
                            if [ "$CAP" -ne 0 ]; then
                                UNLOCKED_APPEND=1
                                Q_MSG=$(queue_text "$MSG")
                                Q_TITLE=$(queue_text "$TITLE")
                                if append_queue "$SESSION" "$KIND" "$PRIORITY" "$TAG" "$Q_TITLE" "$Q_MSG" 0; then
                                    log_send "$KIND" "-" 0 "queued"
                                fi
                            else
                                log_send "$KIND" "-" 0 "halt_skip"
                            fi
                            ;;
                        *) log_send "$KIND" "-" 0 "halt_skip" ;;
                    esac
                fi
            elif [ "$SKIP_CURRENT" -eq 0 ] && [ "$SECONDS" -lt 8 ]; then
                case "$KIND" in
                    final|needs_input|failed|permission|direct)
                        TO_SEND=1
                        LOCK_SEND=1
                        ;;
                    *) log_send "$KIND" "-" 0 "send_fail" ;;
                esac
            fi
        fi

        if [ "$TO_SEND" -eq 1 ]; then
            BODY_FILE=$(mktemp "$USAGE_DIR/.ntfy-body.XXXXXX" 2>/dev/null)
            LEFT=$((8 - SECONDS))
            HTTP="000"
            HTTP_TIME="0"
            CURL_RC=1
            if [ -n "$BODY_FILE" ] && [ "$LEFT" -ge 1 ]; then
                # NEVER: 주제(URL)·헤더·본문을 curl 명령줄 인자로 넘기지 않는다. 명령줄 인자는 ps 에 보인다.
                # curl 설정으로 표준입력(-K -)에 실어 보낸다. printf 는 내장이라 프로세스 목록에 나타나지 않고, data-raw 는 «@파일» 해석을 하지 않는다.
                SEND_TITLE=$(sanitize_text "$SEND_TITLE")
                SEND_MSG=$(sanitize_text "$SEND_MSG")
                RESPONSE=$(printf '%s\n' \
                    "url = \"$(curl_cfg_escape "$NTFY_SERVER/$NTFY_TOPIC")\"" \
                    "header = \"$(curl_cfg_escape "Title: $SEND_TITLE")\"" \
                    "header = \"$(curl_cfg_escape "Priority: $SEND_PRIORITY")\"" \
                    "header = \"$(curl_cfg_escape "Tags: $SEND_TAG")\"" \
                    "data-raw = \"$(curl_cfg_escape "$SEND_MSG")\"" \
                    | curl -sS -K - -o "$BODY_FILE" -w '%{http_code} %{time_total}' \
                        --max-time "$LEFT" 2>/dev/null)
                CURL_RC=$?
                read -r HTTP HTTP_TIME <<< "$RESPONSE"
                [[ "$HTTP" =~ ^[0-9]{3}$ ]] || HTTP="000"
            fi
            RATE_HALT=0
            if [ -n "$BODY_FILE" ] && [ -f "$BODY_FILE" ]; then
                jq -e '.code == 42908' "$BODY_FILE" >/dev/null 2>&1 && RATE_HALT=1
                rm -f "$BODY_FILE" 2>/dev/null || :
            fi
            [ "$RATE_HALT" -eq 1 ] && : > "$HALT_FILE" 2>/dev/null
            ELAPSED_MS=0
            if [[ "$HTTP_TIME" =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
                WHOLE="${HTTP_TIME%%.*}"
                FRACTION="0"
                if [ "$HTTP_TIME" != "$WHOLE" ]; then
                    FRACTION="${HTTP_TIME#*.}000"
                    FRACTION="${FRACTION:0:3}"
                fi
                ELAPSED_MS=$((10#$WHOLE * 1000 + 10#$FRACTION))
            fi

            RQ_RESULT="rate_requeue"
            [ "$RATE_HALT" -eq 1 ] && RQ_RESULT="rate_halt"
            if [ "$HALT_TRIAL" -eq 1 ] && [ "$RATE_HALT" -eq 0 ] &&
               ! { [ "$CURL_RC" -eq 0 ] && [[ "$HTTP" = 2?? ]]; }; then
                T_RETRY="${NTFY_HALT_RETRY_SEC:-3600}"
                [[ "$T_RETRY" =~ ^[0-9]{1,6}$ ]] || T_RETRY=3600
                T_TRIAL="${NTFY_HALT_TRIAL_RETRY_SEC:-300}"
                [[ "$T_TRIAL" =~ ^[0-9]{1,5}$ ]] || T_TRIAL=300
                T_RETRY=$((10#$T_RETRY)); T_TRIAL=$((10#$T_TRIAL))
                [ "$T_TRIAL" -gt "$T_RETRY" ] && T_TRIAL="$T_RETRY"
                touch -d "@$(( $(date +%s) - T_RETRY + T_TRIAL ))" "$HALT_FILE" 2>/dev/null || :
            fi
            if [ "$CURL_RC" -eq 0 ] && [[ "$HTTP" = 2?? ]]; then
                rm -f "$HALT_FILE" 2>/dev/null || :
                if [ "$LOCK_SEND" -eq 1 ]; then
                    log_send "$SEND_KIND" "$HTTP" "$ELAPSED_MS" "lock_send"
                elif [ "$FROM_QUEUE" -eq 1 ]; then
                    log_send "$SEND_KIND" "$HTTP" "$ELAPSED_MS" "flush_sent"
                else
                    log_send "$SEND_KIND" "$HTTP" "$ELAPSED_MS" "sent"
                fi
            else
                REQUEUEABLE=0
                if [ "$HTTP" = "429" ] || [ "$HTTP" = "000" ] ||
                   [[ "$HTTP" = 5?? ]]; then
                    REQUEUEABLE=1
                fi
                if lock_budget; then
                    if [ "$RATE_HALT" -eq 0 ] && [ "$RESERVED" -eq 1 ]; then
                        read_number "$COUNT_FILE"
                        [ "$NUMBER" -gt 0 ] &&
                            printf '%s\n' "$((NUMBER - 1))" > "$COUNT_FILE" 2>/dev/null
                    fi
                    if [ "$CAP" -ne 0 ]; then
                        if [ "$FROM_QUEUE" -eq 1 ]; then
                            [[ "$SEND_TRIES" =~ ^[0-9]+$ ]] || SEND_TRIES=0
                            # WHY: 재시도 가능한 실패(429·000·5xx)에는 훅 경로도 tries 를 올리지 않는다(배송 전용과 같은 기준):
                            # 훅이 장애 중 두 번 실패한 것만으로 최종 보고 줄이 버려지지 않게(2026-10-01 감사 D5)
                            if [ "$REQUEUEABLE" -eq 0 ]; then
                                SEND_TRIES=$((SEND_TRIES + 1))
                            fi
                            if [ "$SEND_TRIES" -ge 2 ]; then
                                log_send "$SEND_KIND" "$HTTP" "$ELAPSED_MS" "retry_drop"
                            elif [ "$REQUEUEABLE" -eq 1 ]; then
                                if append_queue "$SEND_SESSION" "$SEND_KIND" "$SEND_PRIORITY" \
                                    "$SEND_TAG" "$SEND_TITLE" "$SEND_MSG" "$SEND_TRIES" "$SEND_TS"; then
                                    log_send "$SEND_KIND" "$HTTP" "$ELAPSED_MS" "$RQ_RESULT"
                                fi
                            else
                                log_send "$SEND_KIND" "$HTTP" "$ELAPSED_MS" "send_fail"
                            fi
                        else
                            case "$SEND_KIND" in
                                final|needs_input|failed|permission|direct)
                                    if [ "$REQUEUEABLE" -eq 1 ]; then
                                        Q_MSG=$(queue_text "$SEND_MSG")
                                        Q_TITLE=$(queue_text "$SEND_TITLE")
                                        if append_queue "$SEND_SESSION" "$SEND_KIND" "$SEND_PRIORITY" \
                                            "$SEND_TAG" "$Q_TITLE" "$Q_MSG" 0; then
                                            log_send "$SEND_KIND" "$HTTP" "$ELAPSED_MS" "$RQ_RESULT"
                                        fi
                                    else
                                        log_send "$SEND_KIND" "$HTTP" "$ELAPSED_MS" "send_fail"
                                    fi
                                    ;;
                                *) log_send "$SEND_KIND" "$HTTP" "$ELAPSED_MS" "send_fail" ;;
                            esac
                        fi
                    else
                        log_send "$SEND_KIND" "$HTTP" "$ELAPSED_MS" "send_fail"
                    fi
                    unlock_budget
                else
                    if [ "$CAP" -ne 0 ] && [ "$REQUEUEABLE" -eq 1 ]; then
                        case "$SEND_KIND" in
                            final|needs_input|failed|permission|direct)
                                UNLOCKED_APPEND=1
                                if [ "$FROM_QUEUE" -eq 1 ]; then
                                    [[ "$SEND_TRIES" =~ ^[0-9]+$ ]] || SEND_TRIES=0
                                else
                                    SEND_TRIES=0
                                fi
                                if [ "$SEND_TRIES" -ge 2 ]; then
                                    log_send "$SEND_KIND" "$HTTP" "$ELAPSED_MS" "retry_drop"
                                elif append_queue "$SEND_SESSION" "$SEND_KIND" "$SEND_PRIORITY" \
                                    "$SEND_TAG" "$(queue_text "$SEND_TITLE")" \
                                    "$(queue_text "$SEND_MSG")" "$SEND_TRIES" "$SEND_TS"; then
                                    log_send "$SEND_KIND" "$HTTP" "$ELAPSED_MS" "$RQ_RESULT"
                                fi
                                ;;
                            *) log_send "$SEND_KIND" "$HTTP" "$ELAPSED_MS" "send_fail" ;;
                        esac
                    else
                        log_send "$SEND_KIND" "$HTTP" "$ELAPSED_MS" "send_fail"
                    fi
                fi
            fi
        fi
    fi
fi

[ "$SKIP_CURRENT" -eq 1 ] && exit 0

if [ -n "$TMUX" ]; then
    tmux run-shell "printf '\a'" 2>/dev/null
else
    printf '\a' 2>/dev/null
fi

if [ -n "$DISPLAY" ] && command -v notify-send &>/dev/null; then
    notify-send -i dialog-information -u normal "$TITLE" "$MSG" 2>/dev/null &
fi


wait
exit 0
