#!/usr/bin/env bash
# exchange-prune.sh — 외부 모델 교환 폴더(~/grok-exchange · ~/codex-exchange) 자동 정리
# (2026-09-08 사용자 결정 — SessionStart 훅으로 붙는다)
#
# 왜: 교환 폴더는 외부 모델에 보낼 번들·답변이 쌓이는 자리라 계속 커진다. 오래된 번들은
# 다시 쓰이지 않으면서 외부 전송 preflight 의 검사 대상만 늘린다. 기한이 지난 것만 지운다.
#
# 규칙
#   · 대상 = 뿌리 **바로 아래** 항목(파일·디렉터리). 디렉터리는 그 안의 **가장 최근 mtime** 기준.
#   · 보존 = 이름이 `.` 으로 시작하는 항목 전부(`.sessions/` 의 Grok 세션 ID 가 여기 든다) 와
#     `dbg.log`(사용자가 직접 지운다).
#   · 지운 항목은 _audit/exchange-prune.log 에 `날짜<TAB>경로<TAB>mtime` 으로 append.
#   · 뿌리가 없으면 조용히 통과. `--dry-run` 이면 지우지 않고 출력만.
# 환경변수: EXCHANGE_PRUNE_DAYS(기본 14, 양의 정수만) · EXCHANGE_PRUNE_ROOTS(콜론 구분, 테스트용 — 두 교환 폴더 아래만 인정)

set -uo pipefail

PRUNE_DAYS="${EXCHANGE_PRUNE_DAYS:-14}"
ROOTS="${EXCHANGE_PRUNE_ROOTS:-$HOME/grok-exchange:$HOME/codex-exchange}"
LOG="$HOME/.claude/_audit/exchange-prune.log"

# 환경변수 검증 (2026-10-01 감사): 이 스크립트는 `rm -rf` 를 하므로 값이 잘못 들어오면 피해가 크다.
#   · 일수는 양의 정수만 — 0·음수·문자열이면 기한이 «지금» 이 돼 전부 지운다. 어긋나면 기본 14 로 되돌리고 알린다.
#   · 뿌리는 두 교환 폴더(~/grok-exchange · ~/codex-exchange) 자신 또는 그 아래만 — `/`·`$HOME`·`..` 탈출·심볼릭 링크 우회는 realpath 로 풀어 거른다.
[[ "$PRUNE_DAYS" =~ ^[1-9][0-9]*$ ]] || { echo "exchange-prune: EXCHANGE_PRUNE_DAYS 가 양의 정수가 아님 — 기본 14일 사용" >&2; PRUNE_DAYS=14; }
OK_BASES=("$(realpath -m "$HOME/grok-exchange")" "$(realpath -m "$HOME/codex-exchange")")

DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

NOW=$(date +%s)
CUTOFF=$((NOW - PRUNE_DAYS * 86400))

IFS=':' read -r -a ROOT_LIST <<< "$ROOTS"
for ROOT in "${ROOT_LIST[@]}"; do
    [ -d "$ROOT" ] || continue
    REAL_ROOT=$(realpath -m "$ROOT")
    ALLOWED=0
    for BASE in "${OK_BASES[@]}"; do
        case "$REAL_ROOT" in "$BASE"|"$BASE"/*) ALLOWED=1 ;; esac
    done
    [ "$ALLOWED" = "1" ] || { echo "exchange-prune: 교환 폴더 밖 뿌리는 건너뜀: $ROOT" >&2; continue; }
    while IFS= read -r -d '' ITEM; do
        NAME=$(basename "$ITEM")
        case "$NAME" in
            .*|dbg.log) continue ;;   # 보존 대상
        esac
        # 디렉터리는 안쪽까지 훑어 가장 최근 mtime 을 쓴다 — 최근에 쓴 번들을 폴더 mtime 만 보고
        # 지우는 사고를 막는다.
        NEWEST=$(find "$ITEM" -printf '%T@\n' 2>/dev/null | sort -n | tail -1)
        NEWEST=${NEWEST%.*}
        [ -z "$NEWEST" ] && continue
        [ "$NEWEST" -ge "$CUTOFF" ] && continue
        MTIME_ISO=$(date -d "@$NEWEST" '+%Y-%m-%dT%H:%M:%S' 2>/dev/null || echo "$NEWEST")
        if [ "$DRY" = "1" ]; then
            printf '[dry-run] %s\t%s\n' "$ITEM" "$MTIME_ISO"
            continue
        fi
        rm -rf -- "$ITEM" 2>/dev/null || continue
        mkdir -p "$(dirname "$LOG")" 2>/dev/null
        printf '%s\t%s\t%s\n' "$(date '+%Y-%m-%dT%H:%M:%S')" "$ITEM" "$MTIME_ISO" >> "$LOG"
    done < <(find "$ROOT" -mindepth 1 -maxdepth 1 -print0 2>/dev/null)
done

exit 0
