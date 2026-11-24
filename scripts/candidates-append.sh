#!/usr/bin/env bash
# candidates-append.sh — `_evolve/candidates.tsv` 의 유일한 쓰기 경로 (2026-09-14 신설, 2026-10-17 note 열·digest 추가)
#
# 열 (7열, 2026-10-17 G2): id · source · 생성일 · bench_id · status · 요약 · note
#   note 는 «사람·훅이 남긴 처리 기록»(kw=<교정 키워드>, commit=<해시>, effect:… 등) 이다. 요약 열은 중복 판정 키라
#   건드리지 않고 note 를 따로 둔다. 6열 옛 행은 note 가 빈 값으로 읽히고(awk 의 $7), 헤더는 쓰기 때 7열로 올린다.
#   note 정제 순서: 탭·개행→공백 → 나머지 제어문자 제거 → 120자 절단 → 앞뒤 공백 제거. awk 로는 ENVIRON 으로만
#   넘긴다(-v 는 백슬래시를 해석하고, sub 의 치환문은 `&` 를 펼친다 — 사용자 텍스트가 대장을 깨뜨리는 길을 닫는다).
#
# 사용: bash scripts/candidates-append.sh <source> "<요약>" [status=pending] [--note <텍스트>]
#   status 정본 어휘: pending(훅 신규) → pending-bench → pending-approval → accepted | rejected | expired
#   append 의 status 인자는 `pending` 만 받는다(그 밖은 exit 1 «판정 전이는 set»). accepted 로 바로 들어가면 미결 집계에서 빠진다.
#   append 의 --note 는 빈 값·`kw=`·`effect:quiet` 로 시작하는 기계 비고만 받는다. 사람 비고는 expire 보호라 영구 미결을 심을 수 있어 set-note 로만 쓰고,
#   `effect:recurred`(만료 보호 표지)도 append 로는 못 넣는다(usage-check 의 set-note-batch 만 쓴다).
#   append 경로는 요약에서 리터럴 `[note:` 를 지운다(요약에 가짜 note 표지를 심는 위조 차단).
# 종료 코드 표(모든 쓰기 하위 명령 공통, 2026-10-17 Codex 8차): 0 성공 · 1 거부(어휘 밖·전이 불가·id 없음·사용법 오류) · 3 잠금 실패/불가(append 는 중복도 3)
#   · 4 보류(expire 의 미결 T41 집계 전 보류는 --force·--dry-run·선점 10분 초과면 건너뜀, 만료 대상 집계 실패(exit 4)는 --dry-run 도 보류, set-note --only-machine 의 비기계 비고) · 5 대장 저장 실패(임시 파일 생성·쓰기·mv 실패 — 일시적일 수 있어 호출자는 재시도 대상으로 본다).
# 종료: 0=추가(stdout 에 id 1줄) · 3=같은 요약이 이미 있어 건너뜀 또는 잠금 실패(둘은 stderr 의 «잠금 실패» 유무로 구분) · 1=실패(stderr 1줄)
#   실패를 삼키면 «대장이 비었는데 아무도 모른다» 가 다시 생긴다 — 호출자는 stderr 를 막지 않는다.
#
# 상태 전이·갱신 (모두 같은 잠금 안에서 tmp→mv):
#   (append 의 status 인자와 set 의 status 는 둘 다 어휘 밖이면 exit 1. 요약·source·note 는 C0(ESC 포함)·DEL·C1 제어문자를 제거한다.)
#   set <id> <status> [--note <텍스트>] [--machine]   (--note: 기존 비고가 사람 비고면 `<기존>; <새>` 로 덧붙인다. 120자가 모자라면 새 비고가 `commit=` 일 때는 새 비고를 온전히 두고 **기존 비고를 끝에서** 자르고, 그 밖에는 **새 비고 쪽을** 자른다
#       (남는 자리가 2자 미만이면 기존 유지·새 비고 버림, stderr 한 줄). 기계 비고(kw=·effect:)·빈 비고는 교체. --machine: 훅·자동 경로 표시, reviewed-last 를 touch 하지 않는다)
#       **현재 상태가 pending 계열(pending·pending-bench·pending-approval)일 때만** 전이한다(그 밖은 exit 1 —
#       accepted·rejected·expired 를 되돌려 쓰면 판정 이력이 조용히 바뀐다). 상태(+선택 note)를 한 잠금 호출로 바꾼다. 사람 판정 시각이라 candidates-reviewed-last 를 touch 한다(--machine 이면 안 함). 예외: --machine 이 `accepted` + `--note commit=<16진 7자 이상>` 이면 expired 에서도 전이한다(만료와 반영 커밋이 겹칠 때 연결이 사라지지 않게. rejected 는 거부).
#   set-bench <id> <bench_id>            4열(bench_id)만 쓴다. 상태가 pending 계열일 때만(아니면 exit 1), bench_id 는 [A-Za-z0-9._-]{1,40}.
#       사람 판정이 아니므로 reviewed-last 를 touch 하지 않는다. 잠금 1초.
#   set-note [--only-machine] <id> <텍스트>   note 만 교체한다(상태 불변, reviewed-last 불변 — usage-check 의 효과 기록용). --only-machine 은 현재 비고가 effect:recurred 로 시작하면 exit 4(무변경).
#       --only-machine: 잠금 **안에서** 현재 비고가 비었거나 `kw=`·`effect:` 로 시작할 때만 쓰고, 아니면 exit 4 로 무변경(비고를 읽은 뒤
#       잠금 밖에서 판단하면 그 사이 사람 판정·`commit=` 을 덮어쓴다 — 2026-10-17 외부 검토).
#   set-note-batch --only-machine        stdin 의 `id<TAB>텍스트` 여러 줄을 잠금 1회·재작성 1회로 일괄 갱신(기계 비고 행만, 나머지는 조용히 건너뜀).
#       잠금은 최대 3초 대기 후 exit 3. usage-check 는 전체를 `timeout 5 + 행수/100 초(최대 60)` 로 감싼다.
#   flock 이 없으면 잠금 없이 대장을 쓰지 않는다: 쓰기 명령(set·set-note·set-bench·set-note-batch·attach-commit·expire·dedupe-legacy·append) 모두
#       «잠금 불가» stderr 뒤 exit 3.
#   T41 축(role/dim)은 요약의 첫 `:` 앞(앞뒤 공백 제거)이다. oldest-pending 의 축 일치도 같은 규칙이다(usage-check 효과 집계와 동일).
#   잠금 대기 정리(2026-10-17): set·set-note·set-bench·attach-commit·expire 는 `flock -w 1`, dedupe-legacy 는 `flock -w 5`, set-note-batch 는 3초, append 는 `flock -w 5` 이고
#       못 잡으면 대장을 건드리지 않고 exit 3. 무한 대기는 없다(commit-msg/post-commit 훅이 잠금에 걸려 커밋이 멈추던 문제).
#       (--only-machine 은 비고뿐 아니라 **상태도 pending 계열일 때만** 갱신한다. accepted·rejected·expired 행의 비고는 훅이 건드리지 않는다.)
#   attach-commit <id> <해시>            (해시는 [0-9a-f]{7,40} 이고 `git -C ~/.claude cat-file -e <해시>^{commit}` 로 실재해야 한다) 이미 accepted 인 후보의 비고에 `commit=<해시>` 를 붙인다(비고가 있으면 `; commit=<해시>`, 이미 commit= 이 있으면 무변경).
#       승인이 커밋보다 먼저인 흐름(사용자가 먼저 accepted 로 닫고 나중에 커밋)을 post-commit 이 잇는 전용 경로. 상태는 바꾸지 않는다.
#   expire --older-than-days N [--dry-run] [--skip-ids a,b] [--force]
#       보호 두 가지가 expire 자체에 들어 있다(2026-10-17 Codex 4차 — usage-check 말고 스킬이 직접 불러도 우회되지 않게):
#       (a) `_usage/candidates-attach-retry.tsv` 의 id 는 전용 잠금(flock -w 2) 아래에서 읽어 자동 제외(--skip-ids 는 추가분. 잠금 실패면 exit 3).
#       (b) 미결 T41 이 있는데 오늘의 `_usage/t41-effect-<날짜>.d/done` 이 없으면 exit 4 «효과 기록 전이라 만료 보류»(--force·--dry-run·선점 디렉터리가 10분 넘게 done 없이 있는 경우는 이 보류를 건너뛴다. 단 만료 대상 집계 실패(exit 4)는 --dry-run 도 보류한다).
#       status 가 `pending` 이고 생성일이 N일보다 오래된 행만 `expired` 로 바꾼다(삭제 없음). **보호 note 가 있는 행은 건너뛴다**
#       (누군가 검토 중이라는 뜻). 보호 대상은 사람 판정·`commit=` 등 그 밖의 비고뿐이고, 기계가 쓴 비고
#       (`kw=` 로 시작하는 T12 교정 키워드, `effect:` 로 시작하는 T41 효과 기록)는 보호하지 않는다 — 기계 비고가
#       붙었다고 영원히 안 닫히면 안 되기 때문이다(2026-10-17). 단 `effect:recurred` 로 시작하는 행(재발 신호)은 판정 전에
#       사라지지 않게 만료하지 않는다(quiet 은 만료). 자동 만료는 «분석» 이 아니므로 reviewed-last 를 touch 하지 않는다(touch 하면 30일 미판정 경보가
#       영원히 안 울린다). 잠금은 `flock -w 1`, 못 잡으면 대장을 건드리지 않고 exit 3 «잠금 실패»(SessionStart 가 대기로 죽지 않게).
#       `expired` 는 미결 3종(pending·pending-bench·pending-approval)에 들지 않아 CANDIDATES_PENDING 집계에서 빠진다.
#       중복 차단은 expired 행을 **생성일 37일(만료 7일 + 30일) 이내일 때만** 중복으로 본다 — 그보다 오래된 expired 후보가 재발하면 새 행(새 id)으로 다시 들어온다.
#       37일 이내 expired 까지 풀면 correction-detect.sh 가 마지막 400줄의 옛 교정을 만료 직후 오늘 날짜 pending 으로 되살린다(2026-10-17 Codex 2차). 미결·accepted·rejected 는 계속 중복.
#   dedupe-legacy [--dry-run]            T40 행 요약 끝의 ` ×N` 을 한 번 떼어 쓴다(1회 정리용. 행 삭제 없음, 중복 키는 이미 append 가 무시).
#   oldest-pending [--limit N] [--skip N] [--t41-axes "role/dim,role/dim"]
#       미결 3종 중 digest 용 상위 N건(기본 3)을 `id<TAB>type<TAB>요약(60자)` 로 출력. 정렬(2026-11-12): 급이 1차 키 →
#       내용 있는 T41(T41_REPEAT 축 일치가 먼저) > T12 > 그 밖(T40·내용 없는 T41 등), 같은 급에서는 생성일 오름차순 → id.
#       «내용 없는 T41» 은 판정 부분(축 뒤에서 마지막 `from=… |` 까지와 `[orig=…]` 를 뗀 나머지, 소집 설명은 보지 않음)이
#       `RESULT: FAIL 1 target=coder` 같은 판정 표기뿐인 행이다
#       (판정할 정보가 없어 앞줄을 차지하면 digest 가 쓸모없어진다, 2026-11-12 원인 분석 2절).
#       --skip N 은 정렬 뒤 앞 N건을 건너뛴다(기본 0, 날짜 회전용).
#       읽기 전용이라 잠금을 잡지 않는다(대장 교체가 mv 라 반쯤 쓴 파일은 보이지 않는다).
# REF: knowledge/harness/code-history/scripts__candidates-append.sh.md
# shellcheck disable=SC2329  # set_*·attach_commit·expire_rows·dedupe_legacy 는 run_locked "$@" 로 간접 호출됨
set -uo pipefail

EVOLVE_DIR="$HOME/.claude/_evolve"
CAND="$EVOLVE_DIR/candidates.tsv"
LOCK="$EVOLVE_DIR/candidates.lock"
STATUS_VOCAB=" pending pending-bench pending-approval accepted rejected expired "
valid_status() {  # WHY: 정확 일치만 통과. 공백·탭·개행이 든 값은 먼저 거부(부분 문자열 매칭으로 `pending pending-bench` 가 통과하던 결함, 2026-10-17)
    case "$1" in *[[:space:]]*) return 1 ;; esac
    case "$1" in pending|pending-bench|pending-approval|accepted|rejected|expired) return 0 ;; *) return 1 ;; esac
}
NOTE_MAX=120
HEADER=$'id\tsource\t생성일\tbench_id\tstatus\t요약\tnote'

strip_ctrl() {
    LC_ALL=C tr '\t\n\r' '   ' | LC_ALL=C tr -d '\000-\037\177' | LC_ALL=C sed 's/\xc2[\x80-\x9f]//g'
}
clean_note() {  # NEVER: 순서(제어문자 제거 → 절단 → 앞뒤 공백)를 바꾸지 않는다. 순서가 계약이다
    local s
    s=$(printf '%s' "$1" | strip_ctrl)
    {
        local LC_ALL=C.utf8   # NEVER: 바이트로 자르지 않는다. 한글이 깨진다
        s="${s:0:$NOTE_MAX}"
    }
    printf '%s' "$s" | sed 's/^ *//; s/ *$//'
}

swap_cand() {
    if [ "$1" -eq 0 ] && mv "$CAND.tmp.$$" "$CAND"; then return 0; fi
    rm -f "$CAND.tmp.$$"
    echo "candidates-append: 대장 저장 실패 (임시 파일 쓰기 또는 교체 실패: $CAND)" >&2
    return 5
}

clean_text_fast() {
    local s="${1//$'\t'/ }"
    { local LC_ALL=C.utf8; s="${s:0:$NOTE_MAX}"; }
    s="${s#"${s%%[! ]*}"}"; s="${s%"${s##*[! ]}"}"
    CLEAN_OUT="$s"
}
ensure_header() {  # NEVER: 잠금 밖에서 부르지 않는다
    local h
    h=$(head -n 1 "$CAND" 2>/dev/null)
    case "$h" in id$'\t'*) ;; *) return 0 ;; esac
    case "$h" in *$'\t'note) return 0 ;; esac
    awk -F'\t' -v OFS='\t' 'NR==1 && $1=="id" && NF==6 {$7="note"} {print}' "$CAND" > "$CAND.tmp.$$"; swap_cand $? || return 5
}

has_id() {
    ID="$1" awk -F'\t' '$1!="id" && $1==ENVIRON["ID"] {f=1} END {exit f?0:1}' "$CAND" 2>/dev/null
}

touch_reviewed() {
    mkdir -p "$HOME/.claude/_usage" 2>/dev/null && touch "$HOME/.claude/_usage/candidates-reviewed-last" 2>/dev/null
}

# NEVER: 대장 전체를 다시 쓰는 명령을 append 와 같은 잠금 밖에서 돌리지 않는다(임시 파일 → mv, 덮어쓰기 경합).
set_status() {
    valid_status "$2" || { echo "candidates-append: status '$2' 는 어휘 밖(${STATUS_VOCAB})" >&2; return 1; }
    has_id "$1" || { echo "candidates-append: id '$1' 없음" >&2; return 1; }
    # WHY: 전이는 미결(pending 계열)에서만 — accepted·rejected·expired 를 되돌려 쓰면 판정 이력이 조용히 바뀐다(2026-10-17 검수).
    local cur
    cur=$(ID="$1" awk -F'\t' '$1!="id" && $1==ENVIRON["ID"] {print $5; exit}' "$CAND")
    # WHY: 예외(2026-10-17 Grok 4차): 훅·자동 경로(--machine)가 반영 커밋의 해시(`commit=<16진 7자 이상>`)와 함께 accepted 로 보내면 expired 에서도 전이한다.
    # 7일 넘은 pending 을 반영 커밋으로 닫는 순간 다른 세션의 expire 가 먼저 expired 로 바꾸면 연결이 조용히 사라지기 때문이다(반영 커밋이 채택의 증거).
    # rejected 와 accepted 는 여전히 거부한다.
    case "$cur" in
        pending|pending-bench|pending-approval) ;;
        expired)
            local exp_rx='^commit=[0-9a-f]{7,40}($|[;[:space:]])'   # WHY: attach_commit 의 note_rx 와 같은 꼴(끝 경계 포함): `commit=abc1234x` 는 해시가 아니다
            if [ "${5:-0}" = 1 ] && [ "$2" = accepted ] && [ "$3" = 1 ] && [[ "$4" =~ $exp_rx ]]; then :
            else echo "candidates-append: id '$1' 의 현재 상태 '$cur' 는 pending 계열이 아니라 전이할 수 없음" >&2; return 1
            fi ;;
        *) echo "candidates-append: id '$1' 의 현재 상태 '$cur' 는 pending 계열이 아니라 전이할 수 없음" >&2; return 1 ;;
    esac
    # WHY: --note: 기존 비고가 사람 비고(비어 있지 않고 kw=·effect: 도 아님)이면 지우지 않고 `<기존>; <새 비고>` 로 잇는다.
    # 120자가 모자랄 때: 새 비고가 `commit=` 로 시작하면(기계 토큰, 잘리면 해시가 깨진다) 새 비고는 온전히 붙이고 **기존 사람 비고를 끝에서 자른다**.
    # 그 밖의 새 비고는 새 비고 쪽을 자른다(사람 판정이 기계 비고에 밀려 사라지지 않게). 남는 자리가 2자 미만이면 기존 유지·새 비고 버림.
    # (commit= 새 비고가 117자 이상이라 기존 비고를 2자도 못 남기는 경우는 실제 해시 비고(최대 47자)로는 생기지 않으며, 생기면 새 비고만 쓴다.)
    # 기계 비고·빈 비고는 종전처럼 교체. post-commit 의 `set accepted --note commit=…` 가 `hold:` 같은 사람 비고를 지우던 문제.
    local note="$4" curnote avail newpart
    if [ "$3" = 1 ]; then
        curnote=$(ID="$1" awk -F'\t' '$1!="id" && $1==ENVIRON["ID"] {print $7; exit}' "$CAND")
        if ! is_machine_note "$curnote"; then
            if [ -z "$4" ]; then note="$curnote"
            elif [ "${4:0:7}" = "commit=" ]; then
                { local LC_ALL=C.utf8; avail=$((NOTE_MAX - ${#4} - 2)); newpart=""; [ "$avail" -ge 2 ] && newpart="${curnote:0:$avail}"; }
                if [ -n "$newpart" ]; then note=$(clean_note "$newpart; $4")
                else note="$4"; echo "candidates-append: id '$1' 의 commit= 비고가 길어 기존 사람 비고를 남길 자리가 없음 — 새 비고만 기록" >&2
                fi
            else
                { local LC_ALL=C.utf8; avail=$((NOTE_MAX - ${#curnote} - 2)); newpart=""; [ "$avail" -ge 2 ] && newpart="${4:0:$avail}"; }
                if [ -n "$newpart" ]; then note=$(clean_note "$curnote; $newpart")
                else note="$curnote"; echo "candidates-append: id '$1' 의 사람 비고가 길어 새 비고를 붙일 자리가 2자 미만 — 기존 비고 유지, 새 비고 버림" >&2
                fi
            fi
        fi
    fi
    ensure_header || return 5
    ID="$1" ST="$2" HASNOTE="$3" NOTE="$note" awk -F'\t' -v OFS='\t' '
        $1!="id" && $1==ENVIRON["ID"] { $5=ENVIRON["ST"]; if (ENVIRON["HASNOTE"]=="1") $7=ENVIRON["NOTE"] } {print}' \
        "$CAND" > "$CAND.tmp.$$"; swap_cand $? || return 5
    [ "${5:-0}" = 1 ] || touch_reviewed
    echo "$1 -> $2"
}
set_bench() {
    has_id "$1" || { echo "candidates-append: id '$1' 없음" >&2; return 1; }
    local cur
    cur=$(ID="$1" awk -F'\t' '$1!="id" && $1==ENVIRON["ID"] {print $5; exit}' "$CAND")
    case "$cur" in
        pending|pending-bench|pending-approval) ;;
        *) echo "candidates-append: id '$1' 의 현재 상태 '$cur' 는 pending 계열이 아니라 bench_id 를 쓰지 않음" >&2; return 1 ;;
    esac
    ensure_header || return 5
    ID="$1" BID="$2" awk -F'\t' -v OFS='\t' '$1!="id" && $1==ENVIRON["ID"] { $4=ENVIRON["BID"] } {print}' \
        "$CAND" > "$CAND.tmp.$$"; swap_cand $? || return 5
    echo "$1 bench=$2"
}
is_machine_note() {
    case "$1" in ''|kw=*|effect:*) return 0 ;; *) return 1 ;; esac
}
set_note() {
    has_id "$1" || { echo "candidates-append: id '$1' 없음" >&2; return 1; }
    if [ "${3:-0}" = 1 ]; then
        local curnote curst
        curst=$(ID="$1" awk -F'\t' '$1!="id" && $1==ENVIRON["ID"] {print $5; exit}' "$CAND")
        case "$curst" in pending*) ;; *) echo "candidates-append: id '$1' 의 상태 '$curst' 는 pending 계열이 아니라 건드리지 않음" >&2; return 4 ;; esac
        curnote=$(ID="$1" awk -F'\t' '$1!="id" && $1==ENVIRON["ID"] {print $7; exit}' "$CAND")
        is_machine_note "$curnote" || { echo "candidates-append: id '$1' 의 비고는 기계 비고가 아니라 건드리지 않음" >&2; return 4; }
        # WHY: effect:recurred 는 만료 보호 표지라 --only-machine 경로(기계 갱신)만 batch 처럼 덮지 않는다(2026-10-17 Grok 11차). 사람 경로(제3인수 0)는 의도된 덮어쓰기를 허용한다.
        # is_machine_note 는 set --note 의 교체 판정에도 쓰여 그대로 둔다.
        case "$curnote" in effect:recurred*) echo "candidates-append: id '$1' 의 비고는 effect:recurred(만료 보호 표지)라 건드리지 않음" >&2; return 4 ;; esac
    fi
    ensure_header || return 5
    ID="$1" NOTE="$2" awk -F'\t' -v OFS='\t' '
        $1!="id" && $1==ENVIRON["ID"] { $7=ENVIRON["NOTE"] } {print}' \
        "$CAND" > "$CAND.tmp.$$"; swap_cand $? || return 5
    echo "$1 note"
}
set_note_batch() {
    ensure_header || return 5
    # WHY: effect:recurred 비고는 만료 보호 표지라 일괄 갱신도 덮지 않는다(2026-10-17 Grok 10차: usage-check 선정은 이미 제외하지만 직접 호출 경로가 quiet 로 덮을 수 있었다).
    # 묶음은 환경 변수가 아니라 프로세스 치환 파일로 읽는다(단일 환경 변수는 약 128KB 를 넘으면 exec 가 «Argument list too long» 으로 실패 — 4,000행에서 재현).
    awk -F'\t' -v OFS='\t' '
        FILENAME == ARGV[1] { t = index($0, "\t"); if (t > 1) m[substr($0, 1, t - 1)] = substr($0, t + 1); next }
        $1 != "id" && ($1 in m) && $5 ~ /^pending/ && ($7 == "" || $7 ~ /^kw=/ || $7 ~ /^effect:/) && $7 !~ /^effect:recurred/ { $7 = m[$1] } {print}' \
        <(printf '%s' "$1") "$CAND" > "$CAND.tmp.$$"; swap_cand $? || return 5
    echo "note-batch done"
}
attach_commit() {
    has_id "$1" || { echo "candidates-append: id '$1' 없음" >&2; return 1; }
    local cur curnote suffix room base new
    cur=$(ID="$1" awk -F'\t' '$1!="id" && $1==ENVIRON["ID"] {print $5; exit}' "$CAND")
    [ "$cur" = accepted ] || { echo "candidates-append: id '$1' 상태가 accepted 가 아니라 해시를 붙이지 않음" >&2; return 1; }
    curnote=$(ID="$1" awk -F'\t' '$1!="id" && $1==ENVIRON["ID"] {print $7; exit}' "$CAND")
    # NEVER: 실제 해시 모양(`commit=` + 16진수 7자 이상)이 아닌 글을 «이미 있음» 으로 보지 않는다. 사람 비고에 적힌 `commit=나중에` 같은 글이 연결을 막으면 안 된다.
    # 앞 경계(`(^|[;[:space:]])`)를 둔다: `precommit=abc1234` 같은 글이 연결을 막지 않게 한다.
    # 끝 경계(`($|[;[:space:]])`)도 둔다: `commit=abc1234extra` 처럼 해시 뒤에 글이 붙은 것은 «이미 있음» 이 아니다.
    local note_rx='(^|[;[:space:]])commit=[0-9a-f]{7,40}($|[;[:space:]])'
    [[ "$curnote" =~ $note_rx ]] && { echo "$1 commit 이미 있음"; return 0; }
    suffix="commit=$2"
    if [ -z "$curnote" ]; then new="$suffix"
    else
        # WHY: 120자 한도 안에서 해시가 잘리지 않게 기존 비고를 먼저 줄인다
        room=$((NOTE_MAX - ${#suffix} - 2))
        { local LC_ALL=C.utf8; base="${curnote:0:$room}"; }
        new="$base; $suffix"
    fi
    set_note "$1" "$(clean_note "$new")" 0
}
expire_rows() {
    local cut ids n t41_pend edir
    cut=$(date -d "-$1 days" +%Y-%m-%d 2>/dev/null) || { echo "candidates-append: 만료 보류(날짜 계산 실패) — 대장은 건드리지 않음" >&2; return 4; }   # WHY: 입력 오류가 아니라 환경 실패라 종료 코드 표의 4=보류
    # WHY: 효과 기록 전 보류(2026-10-17 Codex 4차): 미결 T41 이 있는데 오늘의 효과 기록 완료 표지(`_usage/t41-effect-<날짜>.d/done`)가 없으면 만료하지 않는다 — exit 4.
    # 8일 된 quiet 행이 재발을 기록받기 전에 expired 가 되는 것을 막는다. --force·--dry-run·선점 디렉터리가 10분 넘게 done 없이 있는 경우(기록 세션 중단)는 이 보류를 건너뛴다.
    # 미리보기(--dry-run)는 파일을 바꾸지 않으므로 이 미결 T41 집계 전 보류는 적용하지 않는다(만료 대상 집계 실패 보류는 아래에서 --dry-run 도 적용).
    if [ "$2" != 1 ] && [ "${4:-0}" != 1 ]; then
        t41_pend=$(awk -F'\t' '$1!="id" && $2=="T41" && ($5=="pending" || $5=="pending-bench" || $5=="pending-approval") {n++} END {print n+0}' "$CAND" 2>/dev/null) || {
            # NEVER: 집계 awk 실패(대장 읽기 실패 등)를 «미결 0» 으로 읽어 보류를 건너뛰지 않는다(2026-10-17): 보호 여부를 알 수 없으니 보류(exit 4).
            echo "candidates-append: 미결 T41 집계 실패라 만료 보류 (대장을 읽지 못함: $CAND) — 대장을 확인한 뒤 다시 하십시오(--force 를 주면 이 보류를 건너뛴다)" >&2
            return 4
        }
        if [ "${t41_pend:-0}" -ge 1 ]; then
            edir="$HOME/.claude/_usage/t41-effect-$(date +%Y-%m-%d).d"
            if [ ! -e "$edir/done" ] && ! { [ -d "$edir" ] && [ -n "$(find "$edir" -maxdepth 0 -mmin +10 2>/dev/null)" ]; }; then
                echo "candidates-append: 효과 기록 전이라 만료 보류 (미결 T41 ${t41_pend}건, 오늘의 t41-effect done 없음) — 세션을 다시 시작하거나 잠시 뒤에 다시 하십시오(--force·--dry-run·선점 10분 초과면 이 보류를 건너뛴다)" >&2
                return 4
            fi
        fi
    fi
    # NEVER: 생성일이 YYYY-MM-DD 모양이 아닌 행을 비교하지 않는다. '-' 같은 값은 문자열 비교에서 항상 «오래됨»으로 읽힌다.
    # 보호 note($7)가 있는 행은 검토 중이라 만료하지 않는다. 빈 note 와 기계 비고(kw=·effect: 시작)는 보호하지 않되,
    # effect:recurred(재발 신호)는 판정 전에 사라지면 안 되므로 만료하지 않는다.
    ids=$(SKIP_IDS="${3:-}" awk -F'\t' -v c="$cut" 'BEGIN { n = split(ENVIRON["SKIP_IDS"], a, ","); for (i = 1; i <= n; i++) if (a[i] != "") skip[a[i]] = 1 }
        $1!="id" && !($1 in skip) && $5=="pending" && ($7=="" || $7 ~ /^kw=/ || $7 ~ /^effect:/) && $7 !~ /^effect:recurred/ && length($3)==10 && $3<c {print $1}' "$CAND" 2>/dev/null) || {
        # NEVER: 대상 집계 awk 실패를 «expire: 0건» 으로 끝내지 않는다(--dry-run 포함, 대장 불변): 보류(exit 4)
        echo "candidates-append: 만료 대상 집계 실패 (대장을 읽지 못함: $CAND) — 대장은 건드리지 않음" >&2
        return 4
    }
    n=$(printf '%s' "$ids" | awk 'NF{n++} END{print n+0}')
    if [ "$2" = 1 ]; then
        echo "expire(dry-run): ${n}건이 expired 로 바뀔 예정 (pending·보호 note·effect:recurred 없음·생성일 < ${cut})"
        [ -n "$ids" ] && printf '%s\n' "$ids"
        return 0
    fi
    if [ "$n" -gt 0 ]; then
        ensure_header || return 5
        SKIP_IDS="${3:-}" awk -F'\t' -v OFS='\t' -v c="$cut" 'BEGIN { n = split(ENVIRON["SKIP_IDS"], a, ","); for (i = 1; i <= n; i++) if (a[i] != "") skip[a[i]] = 1 }
            $1!="id" && !($1 in skip) && $5=="pending" && ($7=="" || $7 ~ /^kw=/ || $7 ~ /^effect:/) && $7 !~ /^effect:recurred/ && length($3)==10 && $3<c {$5="expired"} {print}' "$CAND" > "$CAND.tmp.$$"; swap_cand $? || return 5
    fi
    echo "expire: ${n}건을 expired 로 바꿈 (pending·보호 note·effect:recurred 없음·생성일 < ${cut})"
}
dedupe_legacy() {
    local n
    n=$(awk -F'\t' '$1!="id" && $2=="T40" && $6 ~ / ×[0-9]+$/ {n++} END{print n+0}' "$CAND" 2>/dev/null)
    if [ "$1" = 1 ]; then echo "dedupe-legacy(dry-run): T40 행 ${n}건의 ' ×N' 접미를 뗄 예정"; return 0; fi
    if [ "$n" -gt 0 ]; then
        ensure_header || return 5
        awk -F'\t' -v OFS='\t' '$1!="id" && $2=="T40" && $6 ~ / ×[0-9]+$/ {sub(/ ×[0-9]+$/, "", $6)} {print}' "$CAND" > "$CAND.tmp.$$"; swap_cand $? || return 5
    fi
    echo "dedupe-legacy: T40 행 ${n}건의 ' ×N' 접미를 뗌"
}
oldest_pending() {
    [ -f "$CAND" ] || return 0
    # WHY: 축의 역할 부분을 role-alias.sh 의 normalize_role 로 정규화해 비교한다(history 의 sec-g1/x 와 후보의 security/x 가 같은 축이 되도록 — usage-check 효과 집계와 같은 규칙).
    # role-alias.sh 가 없으면 정규화 없이 원문 비교.
    local axmap="" raw n r norm_axes="" a
    if [ -f "$HOME/.claude/scripts/role-alias.sh" ]; then
        # shellcheck source=/dev/null
        . "$HOME/.claude/scripts/role-alias.sh"
        while IFS= read -r raw; do
            [ -n "$raw" ] || continue
            case "$raw" in */*) r="${raw%%/*}"; n=$(normalize_role "$r"); [ -n "$n" ] || n="$r"; axmap+="$raw"$'\t'"$n/${raw#*/}"$'\n' ;; esac
        done < <(awk -F'\t' 'function trim(x) { gsub(/^[ \t]+|[ \t]+$/, "", x); return x }
            $1!="id" && $2=="T41" { p = index($6, ":"); print trim(p ? substr($6, 1, p - 1) : $6) }' "$CAND" 2>/dev/null | sort -u)
        IFS=',' read -ra norm_axes_arr <<< "$2"
        for a in ${norm_axes_arr[@]+"${norm_axes_arr[@]}"}; do
            a="${a#"${a%%[![:space:]]*}"}"; a="${a%"${a##*[![:space:]]}"}"
            case "$a" in */*) r="${a%%/*}"; n=$(normalize_role "$r"); [ -n "$n" ] || n="$r"; a="$n/${a#*/}" ;; esac
            norm_axes+="${norm_axes:+,}$a"
        done
    else
        norm_axes="$2"
    fi
    AXMAP="$axmap" AXES="$norm_axes" awk -F'\t' 'function trim(x) { gsub(/^[ \t]+|[ \t]+$/, "", x); return x }
        function axis(x,   p) { p = index(x, ":"); return trim(p ? substr(x, 1, p - 1) : x) }
        BEGIN { na = split(ENVIRON["AXES"], ax, ","); for (i = 1; i <= na; i++) ax[i] = trim(ax[i])
                nm = split(ENVIRON["AXMAP"], ml, "\n"); for (i = 1; i <= nm; i++) { split(ml[i], kv, "\t"); if (kv[1] != "") nmap[kv[1]] = kv[2] } }
        function bare(x,   p, r, q, b) { p = index(x, ":"); r = p ? substr(x, p + 1) : x
            while ((q = index(r, "from=")) > 0 && (b = index(substr(r, q), "|")) > 0) r = substr(r, q + b)
            sub(/^[ \t]*(\[orig=[^]]*\][ \t]*)?/, "", r)
            sub(/^((RESULT|STATUS|status|판정)[ \t]*[:=][ \t]*)?(FAIL|BLOCKED|NEEDS_CONTEXT|REJECT)/, "", r)
            gsub(/target=[^ \t]*/, "", r); gsub(/[0-9 \t.,:()-]/, "", r); return r == "" }
        $1!="id" && ($5=="pending" || $5=="pending-bench" || $5=="pending-approval") {
            t = 3
            if ($2 == "T41" && !bare($6)) { t = 1; a6 = axis($6); if (a6 in nmap) a6 = nmap[a6]; for (i = 1; i <= na; i++) if (ax[i] != "" && ax[i] == a6) t = 0 }
            else if ($2 == "T12") t = 2
            print t "\t" $3 "\t" $1 "\t" $2 "\t" $6
        }' "$CAND" 2>/dev/null \
        | LC_ALL=C sort -t$'\t' -k1,1n -k2,2 -k3,3 | tail -n +$(($3 + 1)) | head -n "$1" \
        | while IFS=$'\t' read -r _ _ id typ summ; do
            { local LC_ALL=C.utf8; summ="${summ:0:60}"; }
            printf '%s\t%s\t%s\n' "$id" "$typ" "$summ"
        done
}
run_locked() {
    local w="$1"; shift
    [ -f "$CAND" ] || { echo "candidates-append: 대장 없음 ($CAND)" >&2; return 1; }
    if command -v flock >/dev/null 2>&1; then
        (
            if [ "$w" = 0 ]; then flock 9 || exit 1
            else flock -w "$w" 9 || { echo "candidates-append: 잠금 실패 ($LOCK) — 대장은 건드리지 않음" >&2; exit 3; }
            fi
            "$@"
        ) 9>"$LOCK"
    else
        echo "candidates-append: 잠금 불가 (flock 없음) — 대장은 건드리지 않음" >&2
        return 3
    fi
}
case "${1:-}" in
    set)
        shift
        if [ $# -ge 2 ]; then
            S_ID="$1"; S_ST="$2"; shift 2; S_HAS=0; S_NOTE=""; S_MACH=0; S_OK=1
            while [ $# -gt 0 ]; do
                case "$1" in
                    --note) if [ $# -ge 2 ]; then S_HAS=1; S_NOTE=$(clean_note "$2"); shift 2; else S_OK=0; break; fi ;;
                    --machine) S_MACH=1; shift ;;
                    *) S_OK=0; break ;;
                esac
            done
            if [ "$S_OK" = 1 ]; then run_locked 1 set_status "$S_ID" "$S_ST" "$S_HAS" "$S_NOTE" "$S_MACH"; exit $?; fi
        fi
        echo "candidates-append: 사용법 set <id> <status> [--note <텍스트>] [--machine]" >&2; exit 1 ;;
    set-note)
        shift; ONLY=0
        if [ "${1:-}" = "--only-machine" ]; then ONLY=1; shift; fi
        [ $# -eq 2 ] || { echo "candidates-append: 사용법 set-note [--only-machine] <id> <텍스트>" >&2; exit 1; }
        run_locked 1 set_note "$1" "$(clean_note "$2")" "$ONLY"; exit $? ;;
    set-bench)
        [ $# -eq 3 ] || { echo "candidates-append: 사용법 set-bench <id> <bench_id>" >&2; exit 1; }
        case "$3" in ''|*[!A-Za-z0-9._-]*) echo "candidates-append: bench_id 는 [A-Za-z0-9._-]{1,40} 만" >&2; exit 1 ;; esac
        [ "${#3}" -le 40 ] || { echo "candidates-append: bench_id 는 40자 이하" >&2; exit 1; }
        run_locked 1 set_bench "$2" "$3"; exit $? ;;
    set-note-batch)
        shift
        [ "${1:-}" = "--only-machine" ] || { echo "candidates-append: 사용법 set-note-batch --only-machine (stdin: id<TAB>텍스트)" >&2; exit 1; }
        # WHY: 정제는 행 수와 무관하게 빠르다(2026-10-17 Codex 5차: 행마다 clean_note 서브프로세스를 돌리면 1,000행이 usage-check 의 timeout 에 걸렸다).
        # 제어문자 제거는 입력 전체에 tr·sed 를 한 번씩만 돌리고(탭·개행은 남김, CR 은 공백), 행별 탭→공백·120자 절단·앞뒤 공백 제거는 bash 내장만 쓴다.
        # (clean_note 와 같은 결과: 탭·개행·CR→공백, C0·DEL·C1 제거, 문자 단위 120자 절단, 앞뒤 공백 제거. awk 는 mawk 라 바이트 단위여서 문자 절단에 쓰지 않는다.)
        BATCH_CLEAN=""
        BATCH_IN=$(LC_ALL=C tr '\r' ' ' | LC_ALL=C tr -d '\000-\010\013-\037\177' | LC_ALL=C sed 's/\xc2[\x80-\x9f]//g')
        while IFS= read -r b_line; do
            [ -n "$b_line" ] || continue
            b_id="${b_line%%$'\t'*}"
            [ -n "$b_id" ] || continue
            b_text=""
            [ "$b_line" = "$b_id" ] || b_text="${b_line#*$'\t'}"
            clean_text_fast "$b_text"
            BATCH_CLEAN+="$b_id"$'\t'"$CLEAN_OUT"$'\n'
        done <<< "$BATCH_IN"
        [ -n "$BATCH_CLEAN" ] || exit 0
        run_locked 3 set_note_batch "$BATCH_CLEAN"; exit $? ;;
    attach-commit)
        [ $# -eq 3 ] || { echo "candidates-append: 사용법 attach-commit <id> <해시>" >&2; exit 1; }
        # NEVER: 없는 해시·임의 문자열을 비고에 심지 않는다. 소문자 16진수 7~40자이고 하네스 저장소에 실제 커밋으로 있어야 한다.
        # HARNESS_GIT_DIR 는 시험용 seam(기본 $HOME/.claude).
        case "$3" in ''|*[!0-9a-f]*) echo "candidates-append: 해시는 소문자 16진수만" >&2; exit 1 ;; esac
        [ "${#3}" -ge 7 ] && [ "${#3}" -le 40 ] || { echo "candidates-append: 해시 길이는 7~40자" >&2; exit 1; }
        git -C "${HARNESS_GIT_DIR:-$HOME/.claude}" cat-file -e "$3^{commit}" 2>/dev/null \
            || { echo "candidates-append: 하네스 저장소에 커밋 '$3' 없음" >&2; exit 1; }
        run_locked 1 attach_commit "$2" "$3"; exit $? ;;
    expire)
        shift; DAYS=""; DRY=0; SKIP_IDS=""; FORCE=0
        while [ $# -gt 0 ]; do
            case "$1" in
                --older-than-days) DAYS="${2:-}"; shift 2 || break ;;
                --skip-ids) SKIP_IDS="${2:-}"; shift 2 || break ;;
                --force) FORCE=1; shift ;;
                --dry-run) DRY=1; shift ;;
                *) echo "candidates-append: expire 알 수 없는 인자 '$1'" >&2; exit 1 ;;
            esac
        done
        case "$DAYS" in ''|*[!0-9]*) echo "candidates-append: 사용법 expire --older-than-days N [--dry-run] [--skip-ids a,b]" >&2; exit 1 ;; esac
        case "$SKIP_IDS" in *[!A-Za-z0-9._,-]*) echo "candidates-append: --skip-ids 는 [A-Za-z0-9._-] id 의 쉼표 목록만" >&2; exit 1 ;; esac
        # WHY: 재시도 큐(`_usage/candidates-attach-retry.tsv`)에 있는 id 는 자동으로 제외한다(--skip-ids 는 추가분). 큐 잠금을 **쥔 채로** 대장 잠금을 잡고
        # 재작성까지 끝낸 뒤 둘 다 푼다(2026-10-17 Codex 5차: 큐를 읽고 놓은 뒤 대장 잠금을 기다리는 사이 post-commit 이 큐에 추가하면 옛 목록으로 만료한다).
        # 잠금 순서는 항상 큐 → 대장이다. 생산자(post-commit)는 큐만, set 은 대장만 잡고 큐 소비자는 큐 잠금을 놓은 뒤 set 을 부르므로 교착이 없다.
        # 큐 잠금을 못 잡으면 큐에 뭐가 있는지 모르므로 만료하지 않는다(exit 3). 큐 파일이 아직 없어도 잠금은 잡는다(그 사이 생기는 줄을 놓치지 않게).
        RQ_FILE="$HOME/.claude/_usage/candidates-attach-retry.tsv"
        command -v flock >/dev/null 2>&1 || { echo "candidates-append: 잠금 불가 (flock 없음) — 대장은 건드리지 않음" >&2; exit 3; }
        mkdir -p "$HOME/.claude/_usage" 2>/dev/null
        (
            flock -w 2 8 || { echo "candidates-append: 잠금 실패 (재시도 큐) — 큐의 id 를 알 수 없어 만료하지 않음" >&2; exit 3; }
            Q_IDS=""
            [ ! -e "$RQ_FILE" ] || Q_IDS=$(awk -F'\t' '$1 ~ /^[A-Za-z0-9._-]+$/ { printf "%s%s", (n++ ? "," : ""), $1 }' "$RQ_FILE" 2>/dev/null)
            [ -z "$Q_IDS" ] || SKIP_IDS="${SKIP_IDS:+$SKIP_IDS,}$Q_IDS"
            run_locked 1 expire_rows "$DAYS" "$DRY" "$SKIP_IDS" "$FORCE"
        ) 8>"$HOME/.claude/_usage/candidates-attach-retry.lock"
        exit $? ;;
    dedupe-legacy)
        shift; DRY=0
        [ "${1:-}" = "--dry-run" ] && DRY=1
        run_locked 5 dedupe_legacy "$DRY"; exit $? ;;
    oldest-pending)
        shift; LIMIT=3; AXES=""; SKIP=0
        while [ $# -gt 0 ]; do
            case "$1" in
                --limit) LIMIT="${2:-}"; shift 2 || break ;;
                --skip) SKIP="${2:-}"; shift 2 || break ;;
                --t41-axes) AXES="${2:-}"; shift 2 || break ;;
                *) echo "candidates-append: oldest-pending 알 수 없는 인자 '$1'" >&2; exit 1 ;;
            esac
        done
        case "$LIMIT" in ''|*[!0-9]*) echo "candidates-append: 사용법 oldest-pending [--limit N] [--skip N] [--t41-axes a,b]" >&2; exit 1 ;; esac
        case "$SKIP" in ''|*[!0-9]*) echo "candidates-append: 사용법 oldest-pending [--limit N] [--skip N] [--t41-axes a,b]" >&2; exit 1 ;; esac
        oldest_pending "$LIMIT" "$AXES" "$SKIP"; exit $? ;;
esac

if [ $# -lt 2 ]; then
    echo "candidates-append: 사용법 bash candidates-append.sh <source> \"<요약>\" [status] [--note <텍스트>]" >&2
    exit 1
fi

SRC=$(printf '%s' "$1" | strip_ctrl | sed 's/ *$//')
SUMMARY=$(printf '%s' "$2" | strip_ctrl | sed 's/ *$//')
SUMMARY="${SUMMARY//\[note:/}"
shift 2
STATUS_RAW="pending"; NOTE=""
while [ $# -gt 0 ]; do
    case "$1" in
        --note) NOTE=$(clean_note "${2:-}"); shift 2 || break ;;
        *) STATUS_RAW="$1"; shift ;;
    esac
done
STATUS="$STATUS_RAW"
valid_status "$STATUS" || { echo "candidates-append: status '$STATUS_RAW' 는 어휘 밖(${STATUS_VOCAB})" >&2; exit 1; }
[ "$STATUS" = pending ] || { echo "candidates-append: append 는 pending 만. 판정 전이는 set" >&2; exit 1; }
case "$NOTE" in ''|kw=*|effect:quiet*) ;; *) echo "candidates-append: append 의 비고는 기계 비고만(kw=·effect:quiet). 사람 비고·effect:recurred 는 set-note" >&2; exit 1 ;; esac
if [ -z "$SRC" ] || [ -z "$SUMMARY" ]; then
    echo "candidates-append: source·요약은 빈 값일 수 없습니다" >&2
    exit 1
fi

mkdir -p "$EVOLVE_DIR" 2>/dev/null || { echo "candidates-append: $EVOLVE_DIR 생성 실패" >&2; exit 1; }

append_row() {
    # NEVER: 헤더 없이 append 하지 않는다. 하류 집계가 첫 행을 데이터로 읽는다.
    if [ ! -f "$CAND" ]; then
        printf '%s\n' "$HEADER" > "$CAND" || return 5
    else
        ensure_header || return 5
    fi
    # WHY: 중복 차단: expired 행은 생성일이 37일(만료 7일 + 30일) 이내면 여전히 중복, 그보다 오래되면 재진입 허용(새 행). 미결·accepted·rejected 행과는 계속 중복.
    # T40 요약 끝의 « ×횟수» 는 키에서 뺀다 — 횟수가 바뀔 때마다 같은 패턴이 새 후보가 되던 결함(2026-10-01 감사 P6).
    local cut37
    cut37=$(date -d '-37 days' +%Y-%m-%d 2>/dev/null) || cut37=""
    SUMMARY="$SUMMARY" SRC="$SRC" CUT37="$cut37" awk -F'\t' 'function strip(x) { sub(/ ×[0-9]+$/, "", x); return x }
        BEGIN { s = ENVIRON["SUMMARY"]; src = ENVIRON["SRC"]; c37 = ENVIRON["CUT37"] }
        { a=$6; b=s; if ($2=="T40" && src=="T40") { a=strip(a); b=strip(b) } if (a==b && ($5!="expired" || c37=="" || $3>=c37)) f=1 } END {exit f?0:1}' "$CAND" && return 3
    local stamp seq id
    stamp=$(date +%Y%m%d)
    # NEVER: id 연번을 행 수로 세지 않는다(같은 날 같은 source 의 **최대 연번 +1**). 행 수를 세면 중간 행을 지운 뒤 id 가 겹친다.
    seq=$(awk -F'\t' -v p="$SRC-$stamp-" 'index($1,p)==1 {v=substr($1,length(p)+1)+0; if (v>m) m=v} END {print m+0}' "$CAND")
    id=$(printf '%s-%s-%02d' "$SRC" "$stamp" "$((seq + 1))")
    printf '%s\t%s\t%s\t-\t%s\t%s\t%s\n' "$id" "$SRC" "$(date +%Y-%m-%d)" "$STATUS" "$SUMMARY" "$NOTE" >> "$CAND" || return 5
    printf '%s\n' "$id"
}

if command -v flock >/dev/null 2>&1; then
    exec 9>"$LOCK" || { echo "candidates-append: 잠금 파일 열기 실패 ($LOCK)" >&2; exit 1; }
    # WHY: 최대 5초만 기다린다: SessionStart 의 T12/T40/T41 기록이 잠금 점유자 때문에 멈추지 않게. 못 잡으면 대장은 건드리지 않고 exit 3.
    flock -w 5 9 || { echo "candidates-append: 잠금 실패 ($LOCK) — 대장은 건드리지 않음" >&2; exit 3; }
    append_row
else
    echo "candidates-append: 잠금 불가 (flock 없음) — 대장은 건드리지 않음" >&2
    exit 3
fi
rc=$?
[ "$rc" -eq 5 ] && echo "candidates-append: 대장 저장 실패 ($CAND)" >&2
exit "$rc"
