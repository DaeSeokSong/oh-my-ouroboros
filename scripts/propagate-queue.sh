#!/usr/bin/env bash
# propagate-queue.sh — 하네스 커밋 전파 대기 파일(intent/2026-10-21-harness-change-propagation-gate.md 개정 1)
#
# ■ 왜 필요한가
#   «하네스를 고치면 같은 서버의 다른 세션 전부에 알린다»(CLAUDE.md § 보안, 2026-09-30)가 문장으로만 있어 2026-10-19~21 intent 커밋
#   2건이 전파되지 않았다. 셸에서 다른 세션으로 보내는 공식 CLI 가 없어서(세션 사이 통로는 비공개 형식·토큰) 전달은 받는 쪽이 한다:
#   이 스크립트가 커밋을 대기 파일에 적고, 각 세션의 띠 mod(mods/harness-mod)가 읽어 자기 세션에 알림을 넣은 뒤 받음 기록을 남긴다.
#   커밋한 세션의 턴 종료 훅(scripts/propagate-gate.sh)이 받음 기록을 확인한다.
#
# ■ 하위 명령
#   enqueue                    post-commit 훅이 부른다. HEAD 의 짧은 해시·제목·커밋한 세션 id($CLAUDE_CODE_SESSION_ID, 없으면 빈 값)를
#                              pending.jsonl 에 한 줄 JSON 으로 더한다. 바뀐 파일 가운데 하나라도 config/propagate-paths.txt 의 [behavior] 경로
#                              (디렉터리면 접두, 파일이면 정확히 일치) 아래일 때만 적고, 아니면 적지 않는다(기록용 커밋, intent/2026-11-05-propagate-behavior-files-only.md,
#                              종전 G3 «전부 graphify-out/ 이면 제외» 를 대체). 목록 파일이 없거나 읽지 못하면 안전하게 적는다. 끝에 check-paths 를 부른다.
#                              같은 해시는 다시 적지 않는다(amend 없이 훅이 두 번 돈 경우). 마지막 500줄만 남긴다.
#   check-paths                추적 최상위 경로 가운데 [behavior]·[record] 어디에도 없는 것, 목록에 있으나 저장소에 없는 것을 stderr 한 줄씩
#                              경고한다(종료 코드 0, 커밋을 막지 않음). enqueue 가 하네스 커밋마다 부른다.
#   ack <세션 id> <해시> [manual]  받음 기록을 ack/<세션 id> 에 «해시<TAB>시각<TAB>방식» 한 줄로 더한다. 띠 mod 는 직접 파일을 쓰고,
#                              이 명령은 차단을 받은 main 이 SendMessage 로 직접 알린 뒤 «manual» 로 남길 때 쓴다.
# ■ 분류 목록: $PROPAGATE_PATHS(시험용) 또는 이 스크립트 옆 ../config/propagate-paths.txt
# ■ 위치: $PROPAGATE_DIR(시험용) 또는 ~/.claude/_usage/propagate (기기 로컬, gitignore 된 _usage/). 잠금은 flock -w 2.
# ■ 실패해도 커밋은 막지 않는다(post-commit 은 커밋을 되돌릴 수 없다): 항상 exit 0 이고 사유는 stderr 한 줄.
set -uo pipefail
umask 077   # 대기·받음 기록은 이 사용자만 읽고 쓴다(security 검수 2026-10-21: 기본 umask 002 면 폴더가 775)

DIR="${PROPAGATE_DIR:-$HOME/.claude/_usage/propagate}"
PENDING="$DIR/pending.jsonl"
LOCK="$DIR/.lock"
KEEP=500
SELF_DIR="$(dirname "$(readlink -f "$0" 2>/dev/null || echo "$0")")"
PATHS_FILE="${PROPAGATE_PATHS:-$SELF_DIR/../config/propagate-paths.txt}"
HASH_RX='^[0-9a-f]{7,40}$'
SID_RX='^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'

warn() { echo "⚠ propagate-queue: $*" >&2; }

list_section() {  # $1=목록 파일 $2=절 이름 → 그 절의 항목만 한 줄씩(주석·빈 줄 제외, 앞뒤 공백 제거). 읽기 실패면 비0
    awk -v sec="[$2]" '
        { sub(/^[[:space:]]+/, ""); sub(/[[:space:]]+$/, "") }
        /^#/ || $0 == "" { next }
        /^\[.*\]$/ { cur = $0; next }
        cur == sec { print }
    ' "$1"
}

has_behavior_change() {  # $1=바뀐 파일 목록(줄마다 하나) → 0 하나라도 [behavior] 아래 / 1 없음 / 2 목록을 못 읽거나 [behavior] 가 비어 있음
    local entries f e
    entries=$(list_section "$PATHS_FILE" behavior 2>/dev/null) || return 2
    [ -n "$entries" ] || return 2
    while IFS= read -r f; do
        while IFS= read -r e; do
            case "$e" in
                */) [[ "$f" == "$e"* ]] && return 0 ;;
                *) [ "$f" = "$e" ] && return 0 ;;
            esac
        done <<< "$entries"
    done <<< "$1"
    return 1
}

cmd_check_paths() {  # $1=저장소 뿌리(생략하면 $PROPAGATE_REPO 또는 ~/.claude). 경고만 하고 항상 0
    local repo="${1:-${PROPAGATE_REPO:-$HOME/.claude}}" tops listed t e
    [ -r "$PATHS_FILE" ] || { warn "분류 목록을 읽지 못함($PATHS_FILE) — 분류 점검 생략"; return 0; }
    tops=$(git -c core.quotePath=false -C "$repo" ls-tree HEAD 2>/dev/null \
        | awk -F'\t' '{ split($1, a, " "); print $2 (a[2] == "tree" ? "/" : "") }') || return 0
    [ -n "$tops" ] || return 0
    listed=$(list_section "$PATHS_FILE" behavior; list_section "$PATHS_FILE" record) || return 0
    while IFS= read -r t; do
        grep -Fxq -- "$t" <<< "$listed" || warn "최상위 경로 '$t' 가 config/propagate-paths.txt 의 [behavior]·[record] 어디에도 없음 — config/propagate-paths.txt 를 고치십시오"
    done <<< "$tops"
    while IFS= read -r e; do
        grep -Fxq -- "$e" <<< "$tops" || warn "config/propagate-paths.txt 의 '$e' 가 저장소에 없음 — config/propagate-paths.txt 에서 지우십시오"
    done <<< "$listed"
    return 0
}

cmd_enqueue() {
    local short subject files sid line top want rc
    # 하네스 저장소 커밋만 적는다. 두 경로 모두 실제 경로로 바꿔 비교한다(한쪽만 바꾸면 심볼릭 링크 서버에서 어긋난다, knowledge/harness/path-guard-symlink-bypass.md).
    top=$(git rev-parse --show-toplevel 2>/dev/null) || return 0
    want="${PROPAGATE_REPO:-$HOME/.claude}"
    [ "$(readlink -f "$top")" = "$(readlink -f "$want")" ] || return 0
    cmd_check_paths "$top"   # 분류 점검 경고(커밋은 막지 않음)
    short=$(git rev-parse --short=9 HEAD 2>/dev/null) || { warn "커밋 해시를 읽지 못함 — 전파 대기에 넣지 않음(수동 전파 필요)"; return 0; }
    subject=$(git log -1 --format=%s HEAD 2>/dev/null) || subject=""
    files=$(git -c core.quotePath=false diff-tree --no-commit-id --name-only -r -z -m --root HEAD 2>/dev/null | tr '\0' '\n' | sort -u)
    if [ -n "$files" ]; then
        has_behavior_change "$files"; rc=$?
        case "$rc" in
            1) echo "propagate-queue: 동작 경로 변경 없음(기록용 커밋 $short) — 전파 대기에 넣지 않음" >&2; return 0 ;;
            2) warn "분류 목록을 읽지 못함($PATHS_FILE) — 종전처럼 $short 를 전파 대기에 넣음" ;;
        esac
    fi
    sid="${CLAUDE_CODE_SESSION_ID:-}"
    [[ "$sid" =~ $SID_RX ]] || sid=""
    mkdir -p "$DIR/ack" || { warn "폴더를 만들지 못함: $DIR/ack"; return 0; }
    line=$(jq -cn --arg h "$short" --arg s "${subject:0:200}" --arg a "$sid" --argjson t "$(date +%s)" '{ts:$t, hash:$h, subject:$s, author:$a}') \
        || { warn "jq 로 줄을 만들지 못함"; return 0; }
    (
        flock -w 2 9 || { warn "잠금을 잡지 못함 — $short 를 대기에 넣지 못함(수동 전파 필요)"; exit 0; }
        if [ -f "$PENDING" ] && grep -q "\"hash\":\"$short\"" "$PENDING"; then exit 0; fi
        printf '%s\n' "$line" >> "$PENDING" || { warn "대기 파일에 쓰지 못함"; exit 0; }
        if [ "$(wc -l < "$PENDING")" -gt "$KEEP" ]; then
            tail -n "$KEEP" "$PENDING" > "$PENDING.tmp" && mv "$PENDING.tmp" "$PENDING"
        fi
    ) 9>"$LOCK"
    return 0
}

cmd_ack() {
    local sid="${1:-}" hash="${2:-}" mode="${3:-mod}"
    [[ "$sid" =~ $SID_RX ]] || { warn "세션 id 형식이 아님: $sid"; return 1; }
    [[ "$hash" =~ $HASH_RX ]] || { warn "해시 형식이 아님: $hash"; return 1; }
    case "$mode" in mod|manual|baseline) ;; *) warn "방식은 mod·manual·baseline 중 하나: $mode"; return 1 ;; esac
    mkdir -p "$DIR/ack" || { warn "폴더를 만들지 못함: $DIR/ack"; return 1; }
    printf '%s\t%s\t%s\n' "$hash" "$(date +%s)" "$mode" >> "$DIR/ack/$sid" || { warn "받음 기록을 쓰지 못함"; return 1; }
    echo "받음 기록: $sid $hash ($mode)"
}

case "${1:-}" in
    enqueue) cmd_enqueue; exit 0 ;;
    check-paths) cmd_check_paths; exit 0 ;;
    ack) shift; cmd_ack "$@"; exit $? ;;
    *) echo "사용: $0 enqueue | check-paths | ack <세션 id> <해시> [manual]" >&2; exit 2 ;;
esac
