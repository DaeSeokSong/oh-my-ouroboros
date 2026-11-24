#!/usr/bin/env bash
# propagate-queue.sh — 하네스 커밋 전파: 커밋 훅이 보류 파일에 적고, 하네스 매니저가 모든 작업을 마친 뒤 한 번 대기 파일로 내보낸다.
# 설계: intent/2026-10-21-harness-change-propagation-gate.md 개정 1 · 3. 대기 파일은 각 세션의 띠 mod(mods/harness-mod/hooks/band/propagate.js)가
#   읽어 알림을 넣고 ack 를 남기며, 커밋한 세션의 Stop 훅(scripts/propagate-gate.sh)이 ack 를 확인한다. 규칙: rules-lazy/peer-session-messages.md § 하네스 변경 전파.
#
# 사용:
#   enqueue                    post-commit 훅이 부른다. 하네스 저장소 HEAD 의 짧은 해시 · 제목 · 커밋한 세션 id($CLAUDE_CODE_SESSION_ID)를 held.jsonl 에 한 줄 더한다.
#                              바뀐 파일 가운데 하나라도 config/propagate-paths.txt 의 [behavior] 경로(디렉터리면 접두, 파일이면 정확히 일치) 아래일 때만 적는다.
#                              빈 커밋 · 기록용 커밋 · 이미 있는 해시는 적지 않고, 목록을 못 읽으면 적는다. 끝에 check-paths 를 부른다.
#   release                    held.jsonl 에서 가장 최근 줄부터 HEAD 의 조상인 커밋 하나를 골라 ts 를 지금 · subject 를 그 커밋 제목으로 고쳐 pending.jsonl 에
#                              더하고(같은 해시가 있으면 더하지 않음) held.jsonl 을 비운다. 출력 한 줄: «보류 N건 → 대기 1줄(<해시>)». 제목 글은 출력하지 않는다.
#   held                       «보류 건수<TAB>가장 오래된 줄의 YYYY-MM-DD HH:MM» 한 줄(0건이면 «0»). scripts/harness-usage-check.sh 의 PROPAGATE_HELD 가 부른다.
#   check-paths                추적 최상위 경로 가운데 [behavior] · [record] 어디에도 없는 것, 목록에 있으나 저장소에 없는 것을 stderr 한 줄씩 경고한다.
#   ack <세션 id> <해시> [manual]  ack/<세션 id> 에 «해시<TAB>시각<TAB>방식» 한 줄을 더한다(Stop 훅 차단 뒤 SendMessage 로 직접 알린 main 이 쓴다).
# 줄 형식(held · pending 같음): {"ts":초,"hash":"9자 해시","subject":"제목 앞 200자","author":"세션 id 또는 빈 값"}. held · pending 은 마지막 500줄만 남긴다.
# 파일: $PROPAGATE_DIR(시험용, 기본 ~/.claude/_usage/propagate)의 held.jsonl · pending.jsonl · ack/ · .lock(flock -w 2), 권한은 이 사용자만(umask 077).
#   held · pending 이 링크이거나 일반 파일이 아니면 읽지도 쓰지도 않는다. 분류 목록은 $PROPAGATE_PATHS(시험용), 하네스 저장소는 $PROPAGATE_REPO(시험용).
# 종료 코드: enqueue · check-paths 는 늘 0(커밋을 막지 않음, 사유는 stderr 한 줄). release 는 0(내보냄 · 보류 0건 · 쓸 줄 없음) · 1(잠금 실패 · 링크 ·
#   HEAD 를 못 읽음 · 쓰기 실패). held 는 0, 보류 파일이 링크이거나 일반 파일이 아니면 1. ack 는 형식 오류면 1. 하위 명령이 틀리면 2.
# REF: knowledge/harness/code-history/scripts__propagate-queue.sh.md
set -uo pipefail
umask 077   # WHY: 대기·받음 기록은 이 사용자만 읽고 쓴다(security 검수 2026-10-21: 기본 umask 002 면 폴더가 775)

DIR="${PROPAGATE_DIR:-$HOME/.claude/_usage/propagate}"
PENDING="$DIR/pending.jsonl"
HELD="$DIR/held.jsonl"
LOCK="$DIR/.lock"
KEEP=500
SELF_DIR="$(dirname "$(readlink -f "$0" 2>/dev/null || echo "$0")")"
PATHS_FILE="${PROPAGATE_PATHS:-$SELF_DIR/../config/propagate-paths.txt}"
HASH_RX='^[0-9a-f]{7,40}$'
SID_RX='^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'

warn() { echo "⚠ propagate-queue: $*" >&2; }
plain_or_absent() { [ ! -L "$1" ] && { [ ! -e "$1" ] || [ -f "$1" ]; }; }

list_section() {
    awk -v sec="[$2]" '
        { sub(/^[[:space:]]+/, ""); sub(/[[:space:]]+$/, "") }
        /^#/ || $0 == "" { next }
        /^\[.*\]$/ { cur = $0; next }
        cur == sec { print }
    ' "$1"
}

has_behavior_change() {
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

cmd_check_paths() {
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
    local short subject files sid line top want rc files_rc=0
    # WHY: 두 경로 모두 실제 경로로 바꿔 비교한다. 한쪽만 바꾸면 심볼릭 링크 서버에서 어긋난다(knowledge/harness/path-guard-symlink-bypass.md).
    top=$(git rev-parse --show-toplevel 2>/dev/null) || return 0
    want="${PROPAGATE_REPO:-$HOME/.claude}"
    [ "$(readlink -f "$top")" = "$(readlink -f "$want")" ] || return 0
    cmd_check_paths "$top"
    short=$(git rev-parse --short=9 HEAD 2>/dev/null) || { warn "커밋 해시를 읽지 못함 — 전파 대기에 넣지 않음(수동 전파 필요)"; return 0; }
    subject=$(git log -1 --format=%s HEAD 2>/dev/null) || subject=""
    # WHY: 빈 커밋은 적지 않는다(2026-11-24 보안 검토 N1: `commit --allow-empty` 의 제목만으로 모든 세션에 글이 들어갔다). -m · --root 라 병합 · 첫 커밋도
    #   바뀐 파일이 나오므로 목록이 비는 정상 커밋은 «어느 부모와도 트리가 같은» 커밋뿐이다. diff-tree 가 실패해 빈 경우는 종전처럼 적는다(pipefail).
    files=$(git -c core.quotePath=false diff-tree --no-commit-id --name-only -r -z -m --root HEAD 2>/dev/null | tr '\0' '\n' | sort -u) \
        || files_rc=$?
    if [ -z "$files" ] && [ "$files_rc" -eq 0 ]; then
        echo "propagate-queue: 바뀐 파일이 없는 커밋($short) — 전파 대기에 넣지 않음" >&2; return 0
    fi
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
        flock -w 2 9 || { warn "잠금을 잡지 못함 — $short 를 보류에 넣지 못함(수동 전파 필요)"; exit 0; }
        plain_or_absent "$HELD" || { warn "보류 파일이 링크이거나 일반 파일이 아님 — $short 를 보류에 넣지 않음"; exit 0; }
        if [ -f "$HELD" ] && grep -q "\"hash\":\"$short\"" "$HELD"; then exit 0; fi
        printf '%s\n' "$line" >> "$HELD" || { warn "보류 파일에 쓰지 못함"; exit 0; }
        if [ "$(wc -l < "$HELD")" -gt "$KEEP" ]; then
            tail -n "$KEEP" "$HELD" > "$HELD.tmp" && mv "$HELD.tmp" "$HELD"
        fi
    ) 9>"$LOCK"
    return 0
}

cmd_release() {
    local repo="${PROPAGATE_REPO:-$HOME/.claude}"
    mkdir -p "$DIR" || { warn "폴더를 만들지 못함: $DIR"; return 1; }
    (
        flock -w 2 9 || { warn "잠금을 잡지 못함 — 내보내지 않음"; exit 1; }
        { plain_or_absent "$HELD" && plain_or_absent "$PENDING"; } || { warn "보류 · 대기 파일이 링크이거나 일반 파일이 아님 — 읽지 않음"; exit 1; }
        n=0
        [ -f "$HELD" ] && n=$(grep -c . "$HELD")
        [ "$n" -gt 0 ] || { echo "보류 0건 — 내보낼 것 없음"; exit 0; }
        command -v jq >/dev/null 2>&1 || { warn "jq 없음 — 보류를 그대로 둠"; exit 1; }
        git -C "$repo" rev-parse -q --verify HEAD >/dev/null 2>&1 || { warn "하네스 저장소 HEAD 를 읽지 못함 — 보류를 그대로 둠"; exit 1; }
        out="" h=""
        # WHY: ts 를 내보내는 시각으로 바꾼다. 띠 mod 는 ts 가 세션 시작보다 이르면 알리지 않고(band/propagate.js plan 의 baseline),
        #   Stop 훅은 6시간(scripts/propagate-gate.sh MAX_AGE=21600) 안의 줄만 확인하므로 커밋 시각을 두면 보류 중 뜬 세션이 알림을 못 받는다.
        while IFS= read -r line; do
            h=$(jq -r --arg rx "$SID_RX" 'select(type == "object" and keys_unsorted == ["ts", "hash", "subject", "author"]
                and (.hash | type) == "string" and (.author | type) == "string" and (.author == "" or (.author | test($rx)))) | .hash' <<< "$line" 2>/dev/null) || h=""
            [[ "$h" =~ ^[0-9a-f]{9,40}$ ]] || continue
            git -C "$repo" merge-base --is-ancestor "$h" HEAD 2>/dev/null || continue
            g=$(git -C "$repo" log -1 --format=%s "$h" 2>/dev/null) || continue
            out=$(jq -c --arg s "$g" --argjson t "$(date +%s)" '.ts = $t | .subject = $s[0:200]' <<< "$line" 2>/dev/null) && [ -n "$out" ] && break
            out=""
        done < <(tac "$HELD")
        if [ -z "$out" ]; then
            : > "$HELD"
            echo "보류 ${n}건 → 쓸 줄 없음(HEAD 의 조상인 커밋이 없거나 형식 밖) — 대기에 적지 않고 보류를 비움"; exit 0
        fi
        if [ -f "$PENDING" ] && grep -q "\"hash\":\"$h\"" "$PENDING"; then
            : > "$HELD"
            echo "보류 ${n}건 → 대기에 이미 있음($h) — 더하지 않고 보류를 비움"; exit 0
        fi
        printf '%s\n' "$out" >> "$PENDING" || { warn "대기 파일에 쓰지 못함 — 보류를 그대로 둠"; exit 1; }
        if [ "$(wc -l < "$PENDING")" -gt "$KEEP" ]; then
            tail -n "$KEEP" "$PENDING" > "$PENDING.tmp" && mv "$PENDING.tmp" "$PENDING"
        fi
        : > "$HELD" || warn "보류 파일을 비우지 못함 — 다음 release 는 같은 해시를 대기에 다시 넣지 않음"
        echo "보류 ${n}건 → 대기 1줄($h)"
    ) 9>"$LOCK"
}

cmd_held() {
    local n old
    plain_or_absent "$HELD" || { warn "보류 파일이 링크이거나 일반 파일이 아님 — 읽지 않음"; return 1; }
    n=0
    [ -f "$HELD" ] && n=$(grep -c . "$HELD")
    [ "$n" -gt 0 ] || { echo 0; return 0; }
    old=$(jq -R 'fromjson? | .ts? | numbers | floor' "$HELD" 2>/dev/null | sort -n | head -n 1)
    if [[ "$old" =~ ^[0-9]+$ ]]; then old=$(date -d "@$old" '+%Y-%m-%d %H:%M' 2>/dev/null) || old=-; else old=-; fi
    printf '%s\t%s\n' "$n" "$old"
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
    release) cmd_release; exit $? ;;
    held) cmd_held; exit $? ;;
    check-paths) cmd_check_paths; exit 0 ;;
    ack) shift; cmd_ack "$@"; exit $? ;;
    *) echo "사용: $0 enqueue | release | held | check-paths | ack <세션 id> <해시> [manual]" >&2; exit 2 ;;
esac
