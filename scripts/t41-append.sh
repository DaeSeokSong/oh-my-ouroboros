#!/usr/bin/env bash
# t41-append.sh — agent-eval.md §3 2단계 T41 파일 기록의 유일한 쓰기 경로
#
# 사용법: bash scripts/t41-append.sh <role> <dim> "<signal>"
#         bash scripts/t41-append.sh --from <subagent_type> --signal "<signal>"   (훅 자동 모드)
# 위임 손실 축 (2026-11-24, intent/2026-11-24-harness-review-six-items.md W4): 수동 3인자 기록에만 쓰고 자동 모드는 쓰지 않는다
#   (훅은 지시문과 결과의 어긋남을 판정할 수 없다). 맥락 누락 = 지시문에 없던 정보 때문에 생긴 재작업,
#   방향 이탈 = 지시문에 있었는데 다르게 한 것. 붙여 쓴 꼴(맥락누락 · 방향이탈)은 띄어 쓴 축 이름으로 맞춰 적는다
#   («재작업 가운데 맥락 누락 몇 건» 30일 계수가 철자 차이로 갈라지지 않게). 축 정의 정본: agent-eval.md §2.
#
# 쓰는 쪽 정본: agents/*.md 보고 형식(마지막 text 블록 안 행두 `RESULT: <값>` 한 줄, target=<역할> 선택).
# REJECT 는 `RESULT:`/`STATUS:`/`판정:` 접두형에만 있고 행두 단독형(FAIL|BLOCKED|NEEDS_CONTEXT)에는
# 없다(t41-subagent-stop.sh·agent-spawn-log.sh 의 T41_RX) — A-1 이 항상 `RESULT:` 키를 쓰므로
# 이 비대칭은 무해하다.
# REF: knowledge/harness/code-history/scripts__t41-append.sh.md
set -euo pipefail

usage() {
  echo "사용법: bash scripts/t41-append.sh <role> <dim> \"<signal>\"" >&2
  echo "        bash scripts/t41-append.sh --from <subagent_type> --signal \"<signal>\"" >&2
  echo "        위임 손실 <dim>: 맥락 누락(지시문에 없던 정보 때문에 생긴 재작업) · 방향 이탈(지시문에 있었는데 다르게 한 것)" >&2
}

# WHY: 역할 정규화(`normalize_role`)와 별칭 표의 정본은 role-alias.sh 다(harness-usage-check.sh 8-pre(옛 8c-2)도 같은 파일을 source 한다 — 2026-10-17).
# shellcheck source=/dev/null
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/role-alias.sh"

# WHY: 두 훅(agent-spawn-log=동기, t41-subagent-stop=비동기)이 각자 판단하면
#   같은 신호가 경로에 따라 다른 축에 쌓여 여기 한 곳에서 정한다. 매핑 근거는 agent-eval.md §1 신호표다:
#   검증자(qa·reviewer·security)의 FAIL·REJECT 는 만든 쪽(coder)의 구현 정확성 문제이고,
#   BLOCKED·NEEDS_CONTEXT 는 그 일을 맡은 에이전트 자신의 범위 문제다.
if [[ "${1:-}" == "--from" ]]; then
  if [[ $# -ne 4 || "$3" != "--signal" ]]; then
    usage
    exit 2
  fi
  FROM="$2"; SIGNAL="$4"
  # WHY: 신호 꼴 (2026-11-12): 두 훅은 `<소집 설명 40자> | from=<원 역할> | <RESULT 줄>` 을 넘긴다(설명 칸은 없을 수 있다).
  #   귀속·target= 은 «from=… | » 뒤의 판정 부분(RES)에서만 읽는다. 설명에 FAIL·BLOCKED·target= 같은 낱말이 들어 있어도
  #   축이 바뀌지 않게 하기 위해서다. from= 이 없는 종전 꼴은 신호 전체가 RES 다.
  #   떼는 기준은 넘겨받은 역할 값 그대로의 `from=<FROM> | ` 의 **마지막** 자리다(2026-11-12 검수): 설명 안에 `from=… | …` 꼴 글자가
  #   있어도 진짜 구분자는 설명 뒤에 오므로 가장 긴 접두 제거가 맞다(최단 제거는 설명 속 가짜 구분자에서 끊겼다).
  RES="${SIGNAL}"
  [[ "${SIGNAL}" == *"from=${FROM} | "* ]] && RES="${SIGNAL##*"from=${FROM} | "}"
  # WHY: 역할 정규화를 귀속 판단보다 먼저 적용한다(v2 A-2) — 팀원 이름(qa-p1)이 그대로 넘어오면 아래
  # qa·reviewer·security 비교가 실패해 «검증자 FAIL→coder» 규칙이 죽는다(09-26 qa-p1 실사례).
  FROM_NORM="$(normalize_role "${FROM}")"
  [[ -n "${FROM_NORM}" ]] && FROM="${FROM_NORM}"
  # WHY: herestring — `printf | grep -q` 는 grep 이 먼저 끝나면 printf 가 SIGPIPE 로 죽고 pipefail 이 그
  # 141 을 결과로 삼아 매치를 놓친다(같은 날 correction-detect 에서 재현된 경합).
  # SELF: 이 분기가 «보고 에이전트 자신의 약점» 으로 정했는지의 표지(2026-11-16). 행위자 찾기(t41-ledger.sh find-actor)는
  #   역할 문자열을 다시 비교하지 않고 이 표지로만 자기 귀속을 판단한다(표 밖 역할이 general-purpose 로 바뀌어도 자기 귀속이 유지되게).
  if grep -qE '(BLOCKED|NEEDS_CONTEXT)' <<< "${RES}"; then
    ROLE="${FROM}"; DIM="범위 준수"; SELF=1
  elif grep -qE '(FAIL|REJECT)' <<< "${RES}" \
       && [[ "${FROM}" == "qa" || "${FROM}" == "reviewer" || "${FROM}" == "security" ]]; then
    ROLE="coder"; DIM="구현 정확성"; SELF=0
  else
    ROLE="${FROM}"; DIM="결과 실패"; SELF=1
  fi
  TARGET=$(grep -oE 'target=[A-Za-z0-9_-]+' <<< "${RES}" | head -1 | cut -d= -f2- || true)
  if [[ -n "${TARGET}" ]]; then
    # WHY: main·general-purpose 는 agents/ 파일이 없어도 유효 역할(아래 존재 검사와 같은 예외).
    # 09-26 실측: 첫 실기록 «target=main» 이 normalize_role 빈 값으로 coder 에 오귀속됐다.
    # target= 이 적용되면 «남을 가리킨 것» 이라 자기 귀속 표지를 끈다(target=<같은 역할> 이면 같은 역할의 다른 소집을 찾는다).
    if [[ "${TARGET}" == "main" || "${TARGET}" == "general-purpose" ]]; then
      ROLE="${TARGET}"; SELF=0
    else
      TARGET_NORM="$(normalize_role "${TARGET}")"
      [[ -n "${TARGET_NORM}" ]] && { ROLE="${TARGET_NORM}"; SELF=0; }
    fi
  fi
elif [[ $# -eq 3 ]]; then
  ROLE="$1"; DIM="$2"; SIGNAL="$3"; RES="$3"
  MANUAL=1
else
  usage
  exit 2
fi

CLAUDE_DIR="${HOME}/.claude"
HISTORY="${CLAUDE_DIR}/_audit/history.md"

# WHY: main 은 agents/ 에 파일이 없지만 유효한 역할이다. agent-eval.md 약점 축 표에서 「과잉 위임」의
# 귀속이 main(위임 판단)이라, 파일 존재로만 검증하면 가장 자주 쓸 축의 기록이 영영 0 이 된다.
# general-purpose 도 같은 이유로 허용한다 (2026-09-14): agent-spawn-log.sh 의 자동 T41 호출이
# subagent_type 을 그대로 넘기는데, 실측 소집 200건 중 43건이 agents/ 파일 없는 general-purpose 라
# 파일 존재만 보면 그 43건의 실패 신호가 통째로 버려진다.
if [[ "${ROLE}" != "main" && "${ROLE}" != "general-purpose" ]]; then
  NORM="$(normalize_role "${ROLE}")"
  if [[ -n "${NORM}" ]]; then
    ROLE="${NORM}"
  else
    SIGNAL="[orig=${ROLE}] ${SIGNAL}"
    RES="[orig=${ROLE}] ${RES}"
    ROLE="general-purpose"
  fi
fi

DIM="$(printf '%s' "${DIM}" | tr '\t\n' '  ')"
case "${DIM}" in 맥락누락) DIM="맥락 누락" ;; 방향이탈) DIM="방향 이탈" ;; esac
# WHY: 끝 공백은 뗀다(2026-11-12 실측): agent-spawn-log.sh 의 san 이 RESULT 줄 끝 개행을 공백으로 바꿔 넘겨, 같은 결과가
#   SubagentStop 경로(끝 공백 없음)와 다른 억제 키가 되어 history 에 두 줄 남았다.
SIGNAL="$(printf '%s' "${SIGNAL}" | tr '\t\n' '  ' | sed 's/[[:space:]]*$//')"
RES="$(printf '%s' "${RES}" | tr '\t\n' '  ' | sed 's/[[:space:]]*$//')"

# WHY: 10분 중복 억제 (2026-09-14 재감사 §3-b) — 동기 소집은 PostToolUse 와 SubagentStop 이 **둘 다**
# 같은 결과를 보므로 history 에 같은 신호가 두 줄 남고, T41_REPEAT 의 3회 문턱이 부풀었다.
# history 줄에는 날짜만 있어 «10분 안»을 줄 자체로는 알 수 없어 억제 장부를 _usage/(gitignore) 에 따로 둔다.
# NEVER: 판정 → history append → 장부 기록을 한 임계구역 밖으로 나누지 않는다. 잠금이 없던 종전 판은
# 10병렬에서 같은 신호 10개가 history 에 3~4줄을 남겼다(2026-09-14 재감사 D0).
RECENT="${CLAUDE_DIR}/_usage/t41-recent.tsv"
LOCK="${CLAUDE_DIR}/_usage/t41.lock"
# WHY: 키는 판정 부분(RES)만 쓴다(2026-11-12): 소집 설명은 동기 경로(PostToolUse)에는 있고 SubagentStop 경로에는 없을 수 있어,
#   설명을 키에 넣으면 같은 소집의 두 기록이 서로 다른 키가 되어 억제가 깨진다(T41_REPEAT 3회 문턱이 다시 부푼다).
KEY="${ROLE}/${DIM}|$(printf '%s' "${RES}" | cut -c1-60)"
NOW="$(date +%s)"
LINE=""
mkdir -p "${CLAUDE_DIR}/_usage" 2>/dev/null || true

# WHY: 짧은 id 대장 (2026-11-16, 계획 docs/superpowers/plans/2026-11-16-paper-concepts-eval-loop.md 2절) — 경로 정보는 인자 규약을 바꾸지 않으려고
#   환경변수로 받는다: T41_REPORTER_TP(보고 에이전트 transcript) · T41_SESSION_ID · T41_PATH_KIND(sync|async). 수동 3인자 기록은 path=manual 이고 행위자를 찾지 않는다.
# NEVER: 행위자 찾기를 잠금 안에서 하지 않는다(밖에서 `timeout 2` 로 한다). meta 수백 개를 읽는 동안 t41.lock 을 쥐면 다른 훅이 줄을 서고, 훅 제한(5초) 안에 끝나야 한다.
#   어떤 실패(시간 초과 · jq 없음 · 경로 검사 탈락)든 행위자 빈 칸으로 기록하고 history 기록은 그대로 간다.
LEDGER_SH="${CLAUDE_DIR}/scripts/t41-ledger.sh"
ACTOR=""; ACTOR_TP=""; GAP_S=""; N_CAND=""; PATHK="manual"; REPORTER=""
SESSION="$(printf '%s' "${T41_SESSION_ID:-}" | tr -cd 'A-Za-z0-9-' | cut -c1-64)"
if [[ "${MANUAL:-0}" -ne 1 ]]; then
  case "${T41_PATH_KIND:-}" in sync|async) PATHK="${T41_PATH_KIND}" ;; *) PATHK="auto" ;; esac
  if [[ -n "${T41_REPORTER_TP:-}" ]]; then
    REPORTER="${T41_REPORTER_TP##*/}"; REPORTER="${REPORTER%.jsonl}"
    if command -v timeout >/dev/null 2>&1; then
      { IFS= read -r ACTOR; IFS= read -r ACTOR_TP; IFS= read -r GAP_S; IFS= read -r N_CAND; } \
        < <(T41_SELF="${SELF:-0}" timeout 2 bash "${LEDGER_SH}" find-actor "${T41_REPORTER_TP}" "${ROLE}" 2>/dev/null || true) || true
    fi
  fi
fi

record() {
  if [[ -f "${RECENT}" ]]; then
    if awk -F'\t' -v n="${NOW}" -v k="${KEY}" \
        '$1+0 > n-600 && $2==k { f=1 } END { exit f?0:1 }' "${RECENT}"; then
      return 3
    fi
    if ! { awk -F'\t' -v n="${NOW}" '$1+0 > n-600' "${RECENT}" > "${RECENT}.tmp.$$" \
        && mv "${RECENT}.tmp.$$" "${RECENT}"; }; then rm -f "${RECENT}.tmp.$$"; fi
  fi
  # WHY: id 는 억제 판정을 통과한 뒤에만 만든다 — 두 훅(동기 post · SubagentStop)이 같은 결과를 보면 먼저 쓴 쪽만 id · 대장 행을 받고
  #   뒤쪽은 위 return 3 으로 빠져 대장에 빈 행이 남지 않는다. add 는 같은 임계구역 안에서 부르고 대장 잠금을 겹친다(순서 t41 → ledger).
  # WHY: id 자리: 구분자 « — » 바로 뒤. 재발 계수(harness-usage-check.sh T41_REPEAT · effect)는 « — » 뒤를 지우고 축만 세므로 영향이 없다.
  # NEVER: id 를 KEY · SUMMARY 에 넣지 않는다. 무작위 id 가 들어가면 같은 신호의 10분 억제와 후보 중복 판정이 깨진다.
  local id=""
  id="$(bash "${LEDGER_SH}" add "${SESSION}" "${REPORTER}" "${ACTOR}" "${ACTOR_TP}" "${ROLE}" "${DIM}" "${PATHK}" "${GAP_S}" "${N_CAND}" 9>&-)" || id=""
  [[ "${id}" =~ ^[0-9a-f]{8}$ ]] || id=""
  LINE="- $(date +%Y-%m-%d) T41: ${ROLE}/${DIM} — ${id:+[t41id:${id}] }${SIGNAL}"
  printf '%s\n' "${LINE}" >> "${HISTORY}" || return 1
  printf '%s\t%s\n' "${NOW}" "${KEY}" >> "${RECENT}" || return 1
}

LOCKED=0
if command -v flock >/dev/null 2>&1; then
  if ! { exec 9>"${LOCK}" && flock 9; }; then echo "t41-append: 잠금 실패 (${LOCK})" >&2; exit 1; fi
  LOCKED=1
fi
set +e; record; RC=$?; set -e
# NEVER: 잠금을 닫을 때 `exec 9>&- 2>/dev/null` 처럼 리다이렉션을 덧붙이지 않는다.
# 그 2>/dev/null 이 셸 전체에 남아 아래 경고들이 통째로 사라진다(실측).
if [[ "${LOCKED}" -eq 1 ]]; then exec 9>&-; fi
if [[ "${RC}" -eq 3 ]]; then
  echo "t41-append: 같은 신호가 10분 안에 이미 기록됨 — 건너뜀 (${KEY})" >&2
  exit 0
fi
[[ "${RC}" -eq 0 ]] || { echo "t41-append: history 기록 실패 (${HISTORY})" >&2; exit 1; }
printf '%s\n' "${LINE}"
# WHY: 자동 커밋(2026-11-16)은 백그라운드로 분리해 훅이 커밋 검사 시간만큼 기다리지 않게 한다. 실패해도 이 스크립트의 계약은 그대로.
( bash "${CLAUDE_DIR}/scripts/audit-history-autocommit.sh" >/dev/null 2>&1 & ) || true

# WHY: history.md 는 서술형 감사 기록이라 승인 큐·7일 판정(CANDIDATES_PENDING)·bench 복귀가 읽지 못한다.
# T12(correction-detect)·T40(pattern-detect)이 쓰는 같은 대장에 T41 도 한 행 남겨야 세 갈래가 한 큐에서 판정된다(2026-09-14).
# NEVER: 대장을 직접 cp→mv 하지 않는다. 동시 실행에서 행을 잃었다(재감사 B1). 중복 차단·id 연번·헤더 보장은
# candidates-append.sh 잠금 안에서 하고, 실패는 stdout 만 버리고 stderr 로 드러낸다.
# WHY: 요약 길이 (2026-11-12): 신호 앞에 소집 설명(40자)과 from= 이 붙어 60바이트 절단(cut -c)으로는 한글 설명 20자 안팎에서
#   잘려 from= · RESULT 가 통째로 빠지고 UTF-8 이 반쯤 잘렸다. 120 코드포인트 문자 단위로 자른다(설명 40 + from= + RESULT 앞부분).
SUMMARY="${ROLE}/${DIM}: $(LC_ALL=C.utf8; printf '%s' "${SIGNAL:0:120}")"
bash "${CLAUDE_DIR}/scripts/candidates-append.sh" T41 "${SUMMARY}" >/dev/null || true
