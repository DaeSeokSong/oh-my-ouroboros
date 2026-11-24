#!/usr/bin/env bash
# ci-gate-post-commit.sh — 커밋 ↔ 학습 후보 연결 (2026-10-17 G2·결정 A1)
#   커밋 메시지의 선택 트레일러 `Candidate: <id>` 로 대장(`_evolve/candidates.tsv`)과 커밋을 잇는다.
#   · 트레일러는 사용자가 «커밋해» 지시에 id 를 적었을 때만 main 이 넣는다(skills/commit/SKILL.md). 모델이 스스로 끼워 넣지 않는다.
#   · `Candidate: none` 은 «이 커밋은 후보와 무관» 이라는 명시 표시이며 아무 일도 하지 않는다.
#
# ■ 두 모드
#   1) 훅 모드(인자 없음, .git/hooks/post-commit 심볼릭 링크로 실행): 방금 만든 커밋(HEAD)의 메시지에서 `Candidate: <id>` 를 읽고,
#      검증을 통과하면 `candidates-append.sh set <id> accepted --note "commit=<짧은 해시>" --machine` 를 한 잠금 호출로 실행한다.
#      커밋 해시는 commit-msg 시점에 없으므로 연결은 반드시 post-commit 에서 한다. 이미 accepted 인 id 는 상태를 건드리지 않고,
#      반영 커밋이면서 비고에 commit= 이 없을 때만 `attach-commit` 으로 해시를 붙인다(승인이 커밋보다 먼저인 흐름. amend·rebase 재실행은 첫 해시 유지).
#   2) 검증 모드(`--check <id>`, stdin = 파일 목록): commit-msg 훅이 같은 검증을 재사용한다. 유효하면 exit 0, 아니면 사유 한 줄을 stdout 에 내고 exit 1.
#
# ■ 검증 (둘 다 통과해야 «반영 커밋» 으로 센다 — hit 정의와 같음: agents·rules 계열을 실제로 바꾼 커밋)
#   ① 대장에 id 가 있고 status 가 pending · pending-bench · pending-approval 중 하나
#   ② 파일 목록에 agents/ · rules/ · rules-lazy/ · skills/ · CLAUDE.md 중 하나가 있음
#   expired 도 ② 를 만족하면 통과한다(만료가 검증보다 먼저 끝난 경우. candidates-append.sh set --machine 이 expired→accepted 예외로 전이). rejected 는 거부.
#   `--check` 에서만 accepted 도 통과한다(선승인 흐름): 비고에 이미 commit= 이 있으면(amend·rebase 재실행) 파일과 무관하게 통과하고,
#   없으면 ② 를 만족할 때 «post-commit 이 해시를 붙임» 으로 통과한다. 경고는 id 없음 · expired/rejected · ② 불충족일 때만 나간다.
#
# ■ 머지 커밋: 변경 파일 목록은 `diff-tree -m` 으로 부모마다의 diff 를 합쳐(sort -u) 본다. `-m` 이 없으면 머지 커밋은 목록이 비어 agents/rules 검사가 항상 실패한다.
# ■ 잠금 실패 재시도: `set`/`attach-commit` 이 잠금 실패(exit 3)·대장 저장 실패(exit 5)면, 또는 대장을 읽지 못했는데(validate 반환 2) 거버넌스 파일 변경이 있으면
#   연결이 사라지지 않게 `_usage/candidates-attach-retry.tsv` 에 `id<TAB>해시` 를 한 줄 남긴다
#   (같은 id 는 한 줄, 해시는 최신 커밋으로 교체 — amend·재커밋으로 바뀐 첫 해시는 매달린 커밋이라 연결하면 안 된다). SessionStart(harness-usage-check.sh)가 줄마다 다시 시도해 성공한 줄만 지운다. 큐 파일은 전용 잠금
#   `_usage/candidates-attach-retry.lock`(flock -w 2) 아래에서만 읽고 쓴다. 이 잠금을 못 잡으면 줄을 잃고 stderr 한 줄(커밋은 막지 않는다).
# ■ 변경 파일 목록(diff-tree)이나 커밋 해시(rev-parse)를 못 읽으면 «변경 없음» 으로 오인하지 않고 별도 경고만 내며 큐에는 넣지 않는다(큐 배수는 거버넌스 검증을 하지 않는다).
# ■ 훅 모드의 `set` 은 `--machine` 이다: 자동 연결은 사람 판정이 아니므로 30일 판정 마커(candidates-reviewed-last)를 갱신하지 않는다.
# ■ 실패는 커밋을 막지 않는다 (사용자 답 A1): 훅은 항상 exit 0, 사유는 stderr 경고 한 줄. post-commit 은 어차피 커밋을 되돌릴 수 없다.
# ■ 설치: .git/hooks/post-commit → 이 파일 (scripts/setup-harness.sh 4-c2 가 심볼릭 링크를 만든다)
# ■ 회귀 테스트: python3 ~/.claude/scripts/tests/test_ci_gate_commit_msg.py (트레일러·post-commit 연결 포함)
# REF: knowledge/harness/code-history/scripts__ci-gate-post-commit.sh.md
set -uo pipefail
export LC_ALL=C

CAND="$HOME/.claude/_evolve/candidates.tsv"
GOV_RX='^(agents/|rules/|rules-lazy/|skills/|CLAUDE\.md$)'
SELF_DIR="$(dirname "$(readlink -f "$0" 2>/dev/null || echo "$0")")"

RETRY_F="$HOME/.claude/_usage/candidates-attach-retry.tsv"
RETRY_LOCK="$HOME/.claude/_usage/candidates-attach-retry.lock"
queue_retry() {
    command -v flock >/dev/null 2>&1 || return 2   # NEVER: 무잠금으로 쓰면 소비자와 경합하므로 성공(0)으로 가장하지 않는다
    mkdir -p "$HOME/.claude/_usage" 2>/dev/null
    (
        flock -w 2 8 || exit 1
        if ID="$1" awk -F'\t' '$1==ENVIRON["ID"] {f=1} END {exit f?0:1}' "$RETRY_F" 2>/dev/null; then
            # NEVER: 같은 id 의 옛 해시를 남기지 않는다. amend 로 해시가 바뀐 뒤 다시 실패하면 옛 해시만 남았다.
            ID="$1" NEWH="$2" awk -F'\t' -v OFS='\t' '$1==ENVIRON["ID"] { $2 = ENVIRON["NEWH"] } {print}' "$RETRY_F" > "$RETRY_F.tmp.$$" 2>/dev/null || { rm -f "$RETRY_F.tmp.$$"; exit 3; }
            mv "$RETRY_F.tmp.$$" "$RETRY_F" || { rm -f "$RETRY_F.tmp.$$"; exit 3; }
            exit 0
        fi
        printf '%s\t%s\n' "$1" "$2" >> "$RETRY_F" || exit 3
    ) 8>"$RETRY_LOCK"
}
queue_why() {
    case "$1" in 2) echo '잠금 불가: flock 없음' ;; 3) echo '큐 쓰기 실패' ;; *) echo '큐 잠금 실패' ;; esac
}

validate() {
    local id="$1" st files
    case "$id" in ''|*[!A-Za-z0-9._-]*) echo "id 형식이 올바르지 않음: '$id'"; return 1 ;; esac
    [ -f "$CAND" ] || { echo "후보 대장 없음 ($CAND)"; return 1; }
    [ -r "$CAND" ] || { echo "대장 읽기 실패 ($CAND)"; return 2; }   # NEVER: 읽을 수 없는 대장을 «대장에 id 없음» 으로 돌리지 않는다(2 = 일시 실패)
    st=$(ID="$id" awk -F'\t' '$1!="id" && $1==ENVIRON["ID"] {print $5; exit}' "$CAND") || { echo "대장 읽기 실패 (awk 실패: $CAND)"; return 2; }   # NEVER: 읽히는 대장에서 awk 가 실패한 것을 «id 없음» 으로 돌리지 않는다(일시 실패)
    [ -n "$st" ] || { echo "대장에 id '$id' 없음"; return 1; }
    files=$(cat)
    case "$st" in
        pending|pending-bench|pending-approval) ;;
        accepted)
            # NEVER: note_rx 의 앞 경계(`(^|[;[:space:]])`)를 빼지 않는다. `precommit=abc1234` 같은 글을 이미 연결된 것으로 오탐한다.
            local note_rx='(^|[;[:space:]])commit=[0-9a-f]{7,40}($|[;[:space:]])' cur_note
            cur_note=$(ID="$id" awk -F'\t' '$1!="id" && $1==ENVIRON["ID"] {print $7; exit}' "$CAND") || { echo "대장 읽기 실패 (awk 실패: $CAND)"; return 2; }
            if [[ "$cur_note" =~ $note_rx ]]; then echo "이미 accepted, 비고에 commit=<해시> 가 있어 유지됨"; return 0; fi
            printf '%s\n' "$files" | grep -E "$GOV_RX" >/dev/null || { echo "agents/·rules/·rules-lazy/·skills/·CLAUDE.md 변경이 없는 커밋이라 후보 반영으로 인정하지 않음"; return 1; }
            echo "이미 accepted, post-commit 이 해시를 붙임"; return 0 ;;
        expired)
            # WHY: 만료가 반영 커밋 검증보다 먼저 끝난 경우 반영 커밋이 채택의 증거이므로 agents/rules 계열 변경이 있으면 통과시킨다(2026-10-17 Codex 6차).
            printf '%s\n' "$files" | grep -E "$GOV_RX" >/dev/null || { echo "agents/·rules/·rules-lazy/·skills/·CLAUDE.md 변경이 없는 커밋이라 후보 반영으로 인정하지 않음"; return 1; }
            echo "이미 expired, 반영 커밋이므로 accepted 로 전이함"; return 0 ;;
        *) echo "id '$id' 의 상태가 '$st' (pending·pending-bench·pending-approval 만 연결 가능)"; return 1 ;;
    esac
    printf '%s\n' "$files" | grep -E "$GOV_RX" >/dev/null || { echo "agents/·rules/·rules-lazy/·skills/·CLAUDE.md 변경이 없는 커밋이라 후보 반영으로 인정하지 않음"; return 1; }
    return 0
}

if [ "${1:-}" = "--check" ]; then
    validate "${2:-}"; exit $?
fi

# WHY: 하네스 변경 전파 대기에는 후보 연결보다 먼저, 후보가 없는 커밋도 빠짐없이 적는다(intent/2026-10-21-harness-change-propagation-gate.md).
# 실패해도 커밋·후보 연결을 막지 않는다(사유는 그 스크립트가 stderr 에 한 줄).
bash "$(dirname "$(readlink -f "$0")")/propagate-queue.sh" enqueue || true

MSG=$(git log -1 --format=%B 2>/dev/null) || exit 0
ID=$(printf '%s\n' "$MSG" | grep -v '^#' | grep -E '^Candidate:[[:space:]]*[^[:space:]]+[[:space:]]*$' | head -n1 \
    | sed -E 's/^Candidate:[[:space:]]*//; s/[[:space:]]*$//')
[ -n "$ID" ] && [ "$ID" != "none" ] || exit 0

# WHY: -z(NUL 구분)가 없으면 한글 같은 비ASCII 경로가 `"\355…"` 인용형으로 나와 GOV_RX 를 빠져나간다(2026-10-17 외부 검토).
# 첫 커밋(부모 없음)에서도 읽도록 --root 를 쓰고, -m 으로 머지 커밋도 부모마다의 diff 를 합쳐 본다.
FILES=$(git -c core.quotePath=false diff-tree --no-commit-id --name-only -r -z -m --root HEAD 2>/dev/null | tr '\0' '\n' | sort -u); FILES_RC=$?
SHORT=$(git rev-parse --short=7 HEAD 2>/dev/null); SHORT_RC=$?   # WHY: 하한 7: core.abbrev<7 이어도 commit=<16진 7자 이상> 정규식에 걸리게
if [ "$SHORT_RC" -ne 0 ] || [ -z "$SHORT" ]; then
    echo "⚠ ci-gate-post-commit: 커밋 해시를 읽지 못함(rev-parse rc=$SHORT_RC) — 수동: bash scripts/candidates-append.sh set $ID accepted --note commit=<해시> --machine (이미 accepted 면 attach-commit $ID <해시>, 커밋은 유지됨)" >&2
    exit 0
fi
# NEVER: diff-tree 실패를 «변경 없음» 으로 보거나 큐에 넣지 않는다. 큐 배수는 agents/rules 검증을 하지 않으므로 넣으면 미검증 채택이 된다.
if [ "$FILES_RC" -ne 0 ]; then
    echo "⚠ ci-gate-post-commit: 변경 파일 목록을 읽지 못함(diff-tree rc=$FILES_RC) — 수동: bash scripts/candidates-append.sh set $ID accepted --note commit=$SHORT --machine (이미 accepted 면 attach-commit $ID $SHORT, 커밋은 유지됨)" >&2
    exit 0
fi

if [ -f "$CAND" ]; then
    CUR=$(ID="$ID" awk -F'\t' '$1!="id" && $1==ENVIRON["ID"] {print $5; exit}' "$CAND")
    if [ "$CUR" = "accepted" ]; then
        if printf '%s\n' "$FILES" | grep -E "$GOV_RX" >/dev/null; then
            bash "$SELF_DIR/candidates-append.sh" attach-commit "$ID" "$SHORT" >/dev/null; RC=$?
            if [ "$RC" -eq 3 ] || [ "$RC" -eq 5 ]; then
                queue_retry "$ID" "$SHORT"; QRC=$?
                if [ "$QRC" -eq 0 ]; then
                    echo "⚠ ci-gate-post-commit: 후보 $ID 에 commit=$SHORT 를 붙이지 못함($([ "$RC" -eq 5 ] && echo '대장 저장 실패' || echo '잠금 실패')) — 재시도 큐에 넣음, 다음 세션이 다시 시도" >&2
                else
                    echo "⚠ ci-gate-post-commit: 재시도 큐 기록 실패 — 연결 누락($(queue_why "$QRC"), 후보 $ID, 커밋은 유지됨), 수동: bash scripts/candidates-append.sh attach-commit $ID $SHORT" >&2
                fi
            elif [ "$RC" -ne 0 ]; then
                echo "⚠ ci-gate-post-commit: 후보 $ID 에 commit=$SHORT 를 붙이지 못함 — 커밋은 유지됨" >&2
            fi
        else
            echo "⚠ ci-gate-post-commit: 후보 $ID 는 accepted 이나 이 커밋은 거버넌스 파일 변경이 없어 commit= 을 붙이지 않음" >&2
        fi
        exit 0
    fi
fi

REASON=$(printf '%s\n' "$FILES" | validate "$ID"); VRC=$?
if [ "$VRC" -eq 0 ]; then
    bash "$SELF_DIR/candidates-append.sh" set "$ID" accepted --note "commit=$SHORT" --machine >/dev/null; RC=$?
    if [ "$RC" -eq 3 ] || [ "$RC" -eq 5 ]; then
        queue_retry "$ID" "$SHORT"; QRC=$?
        if [ "$QRC" -eq 0 ]; then
            echo "⚠ ci-gate-post-commit: 후보 $ID 를 accepted 로 바꾸지 못함($([ "$RC" -eq 5 ] && echo '대장 저장 실패' || echo '잠금 실패')) — 재시도 큐에 넣음, 다음 세션이 다시 시도" >&2
        else
            echo "⚠ ci-gate-post-commit: 재시도 큐 기록 실패 — 연결 누락($(queue_why "$QRC"), 후보 $ID, 커밋은 유지됨), 수동: bash scripts/candidates-append.sh set $ID accepted --note commit=$SHORT --machine" >&2
        fi
    elif [ "$RC" -ne 0 ]; then
        echo "⚠ ci-gate-post-commit: 후보 $ID 를 accepted 로 바꾸지 못함 — 커밋은 유지됨. 수동: bash scripts/candidates-append.sh set $ID accepted --note commit=$SHORT --machine" >&2
    fi
elif [ "$VRC" -eq 2 ]; then
    if printf '%s\n' "$FILES" | grep -E "$GOV_RX" >/dev/null; then
        queue_retry "$ID" "$SHORT"; QRC=$?
        if [ "$QRC" -eq 0 ]; then
            echo "⚠ ci-gate-post-commit: 후보 $ID 의 상태를 확인하지 못함(대장 읽기 실패) — 재시도 큐에 넣음, 다음 세션이 다시 시도" >&2
        else
            echo "⚠ ci-gate-post-commit: 재시도 큐 기록 실패 — 연결 누락($(queue_why "$QRC"), 대장 읽기 실패, 후보 $ID, 커밋은 유지됨), 수동: bash scripts/candidates-append.sh set $ID accepted --note commit=$SHORT --machine" >&2
        fi
    else
        echo "⚠ ci-gate-post-commit: Candidate: $ID 연결 안 함 — $REASON, 거버넌스 파일 변경도 없어 큐에 넣지 않음 (커밋은 유지됨)" >&2
    fi
else
    echo "⚠ ci-gate-post-commit: Candidate: $ID 연결 안 함 — $REASON (커밋은 유지됨)" >&2
fi
exit 0
