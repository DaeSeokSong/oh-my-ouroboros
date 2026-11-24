#!/usr/bin/env bash
# ontology-commit.sh — 나이틀리가 스테이징해 둔 온톨로지 자동 추출분(graphify-out/)을 한 번에 커밋한다. (2026-11-24 신설)
#
# 무엇을: 스테이징된 graphify-out/ 변경을 graphify-out/.commit-msg 로 커밋하고, 감시 서명을 남기고,
#   커밋하지 않은 knowledge/ 변경 목록을 보여 준다. 인자 없이 부르면 미리보기만 하고 아무것도 바꾸지 않는다.
# 어떻게: --apply --reason "<사용자 지시 인용>" 으로만 커밋한다. 순서는
#   index.lock 확인(3) → 메시지 파일 확인(4) → 스테이징 0건이면 종료(0) → 스테이징 밖 변경 확인(6)
#   → git commit -F 메시지 -- graphify-out/ → 저장소 뿌리로 이동해 감시 서명 → knowledge/ 남은 목록 안내.
#   knowledge/ 는 커밋하지 않는다(다른 세션이 쓴 것일 수 있어 사람이 내용을 본 뒤 따로 커밋). push 도, graphify update 도 하지 않는다.
# 왜: 사용자가 «온톨로지 변경사항 커밋» 을 네 번 지시했고 매번 같은 손 절차였다. 같은 입력이면 같은 결과가 나와야 하는 절차는
#   글이 아니라 스크립트로 둔다(2026-11-24 사용자 지시).
#   스테이징 밖 변경을 막는 까닭: `git commit -- graphify-out/` 는 스테이징하지 않은 그 경로의 변경도 함께 싣는데
#   미리보기 건수는 스테이징분만 세므로, 야간 추출 뒤 누가 고친 파일이 모르는 사이 섞일 수 있다.
#
# 알아 둘 것
#   - 자동 추출분 커밋은 파일이 9천 개 안팎이라 300초를 넘길 수 있다. 부르는 쪽이 백그라운드로 돌린다.
#   - 하네스 그래프는 나이틀리 자동 갱신 전용이다. 수동 갱신(graphify update)을 하지 않는다.
#   - 사용자가 «온톨로지 변경사항 커밋» 을 지시했을 때 main 이 돌린다.
#   - --reason 값은 감시 서명 스크립트의 인자로만 넘기고 git 명령에는 끼우지 않는다.
#   - .commit-msg 가 심볼릭 링크면 거부한다(링크 대상의 내용을 읽거나 출력하지 않는다).
#
# 종료 코드: 0 정상(커밋 없음 포함) · 2 인자 오류(--reason 누락 · 시험 표지 없이 환경 변수 설정 포함)
#   · 3 index.lock 있음 · 4 메시지 파일 없음/빔/심볼릭 링크 · 5 커밋은 됐으나 감시 서명 실패
#   · 6 스테이징 뒤 바뀐 graphify-out/ 추적 파일이 있어 커밋하지 않음
#   · git 자체가 실패하면 git 의 종료 코드(예: 128)를 그대로 낸다.
# 시험용 환경 변수: ONTOLOGY_COMMIT_REPO(저장소 뿌리) · ONTOLOGY_COMMIT_OVERSIGHT(감시 서명 스크립트)는
#   ONTOLOGY_COMMIT_TEST=1 일 때만 읽는다. 표지 없이 둘 중 하나가 설정돼 있으면 조용히 무시하지 않고 종료 코드 2.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
if [ "${ONTOLOGY_COMMIT_TEST:-}" = "1" ]; then
    REPO="${ONTOLOGY_COMMIT_REPO:-$(cd "$SCRIPT_DIR/.." && pwd -P)}"
    OVERSIGHT="${ONTOLOGY_COMMIT_OVERSIGHT:-$SCRIPT_DIR/oversight-append.sh}"
elif [ -n "${ONTOLOGY_COMMIT_REPO:-}" ] || [ -n "${ONTOLOGY_COMMIT_OVERSIGHT:-}" ]; then
    echo "ONTOLOGY_COMMIT_REPO / ONTOLOGY_COMMIT_OVERSIGHT 는 ONTOLOGY_COMMIT_TEST=1 일 때만 읽습니다. 변수를 해제하십시오" >&2
    exit 2
else
    REPO="$(cd "$SCRIPT_DIR/.." && pwd -P)"
    OVERSIGHT="$SCRIPT_DIR/oversight-append.sh"
fi
MSG_REL="graphify-out/.commit-msg"

APPLY=0
REASON=""
while [ $# -gt 0 ]; do
    case "$1" in
        --apply) APPLY=1; shift ;;
        --reason) [ $# -ge 2 ] || { echo "--reason 에 값이 없습니다" >&2; exit 2; }; REASON="$2"; shift 2 ;;
        *) echo "사용법: bash scripts/ontology-commit.sh [--apply --reason \"<사용자 지시 인용>\"]" >&2; exit 2 ;;
    esac
done

if [ "$APPLY" -eq 1 ] && [ -z "$REASON" ]; then
    echo "--apply 에는 --reason \"<사용자 지시 인용>\" 이 필요합니다" >&2
    exit 2
fi

git_() { git --no-optional-locks -C "$REPO" "$@"; }

LOCK="$(git_ rev-parse --path-format=absolute --git-path index.lock)"
STAGED="$(git_ diff --cached --name-status -M -- graphify-out/ | cut -c1)"
N_UNSTAGED="$(git_ diff --name-only -- graphify-out/ | awk 'END{print NR}')"
count() { printf '%s\n' "$STAGED" | awk -v k="$1" '$1==k{n++} END{print n+0}'; }
N_M=$(count M); N_A=$(count A); N_D=$(count D); N_R=$(count R)
N_ALL=$((N_M + N_A + N_D + N_R + $(count C) + $(count T)))
MSG_LINK=0
[ -L "$REPO/$MSG_REL" ] && MSG_LINK=1
MSG_FIRST=""
if [ "$MSG_LINK" -eq 0 ] && [ -s "$REPO/$MSG_REL" ]; then MSG_FIRST="$(head -n 1 "$REPO/$MSG_REL")"; fi
KNOWLEDGE="$(git_ status --porcelain -- knowledge/)"

show_knowledge() {
    if [ -n "$KNOWLEDGE" ]; then
        echo "knowledge/ 변경 (추적 안 됐거나 바뀐 파일):"
        printf '%s\n' "$KNOWLEDGE" | sed 's/^/  /'
    else
        echo "knowledge/ 변경: 없음"
    fi
}

if [ "$APPLY" -eq 0 ]; then
    if [ "$MSG_LINK" -eq 1 ]; then
        echo "${MSG_REL} 가 심볼릭 링크라 거부합니다 (대상 내용은 읽지 않았습니다)" >&2
        exit 4
    fi
    echo "[미리보기] 아무것도 바꾸지 않았습니다"
    echo "스테이징된 graphify-out/ 변경: 총 ${N_ALL}건 (수정 ${N_M} · 추가 ${N_A} · 삭제 ${N_D} · 이름 바꿈 ${N_R})"
    echo "스테이징 뒤 바뀐 graphify-out/ 추적 파일: ${N_UNSTAGED}건 (0이 아니면 --apply 가 거부합니다)"
    echo "커밋 메시지(${MSG_REL}) 첫 줄: ${MSG_FIRST:-(없음 또는 빈 파일)}"
    show_knowledge
    if [ -e "$LOCK" ]; then echo ".git/index.lock: 있음 (다른 커밋이 도는 중)"; else echo ".git/index.lock: 없음"; fi
    echo "커밋하려면: bash scripts/ontology-commit.sh --apply --reason \"<사용자 지시 인용>\" (백그라운드로)"
    exit 0
fi

if [ -e "$LOCK" ]; then
    echo "다른 커밋이 도는 중입니다 (${LOCK} 있음). 끝난 뒤 다시 부르십시오" >&2
    exit 3
fi
if [ "$MSG_LINK" -eq 1 ]; then
    echo "${MSG_REL} 가 심볼릭 링크라 거부합니다 (대상 내용은 읽지 않았습니다)" >&2
    exit 4
fi
if [ -z "$MSG_FIRST" ]; then
    echo "${MSG_REL} 가 없거나 비어 있습니다. 나이틀리가 아직 준비하지 않았습니다" >&2
    exit 4
fi
if [ "$N_ALL" -eq 0 ]; then
    echo "커밋할 것 없음 (스테이징된 graphify-out/ 변경 0건)"
    exit 0
fi
if [ "$N_UNSTAGED" -ne 0 ]; then
    echo "스테이징 뒤 바뀐 파일 ${N_UNSTAGED}건: 야간 추출 뒤 누가 고쳤는지 확인하라 (git diff --name-only -- graphify-out/)" >&2
    exit 6
fi

git_ commit -q -F "$MSG_REL" -- graphify-out/
HASH="$(git_ rev-parse --short=7 HEAD)"
echo "커밋 완료: ${HASH} ${MSG_FIRST} (${N_ALL}건)"

SIGN_RC=0
(cd "$REPO" && bash "$OVERSIGHT" commit "${HASH} 온톨로지 자동 추출분" "$REASON" main) || SIGN_RC=$?
if [ "$SIGN_RC" -ne 0 ]; then
    echo "경고: 커밋은 됐으나 감시 서명이 실패했습니다 (종료 코드 ${SIGN_RC}). 서명을 따로 남기십시오" >&2
fi

KNOWLEDGE="$(git_ status --porcelain -- knowledge/)"
show_knowledge
echo "이 변경은 내용을 확인한 뒤 따로 커밋한다 (이 스크립트는 knowledge/ 를 커밋하지 않습니다)"
[ "$SIGN_RC" -eq 0 ] || exit 5
