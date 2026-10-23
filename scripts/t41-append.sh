#!/usr/bin/env bash
# t41-append.sh — agent-eval.md §3 2단계 T41 파일 기록의 유일한 쓰기 경로
#
# 왜 스크립트인가: bash-write-check 훅이 명령줄의 `>>` 리다이렉션을 막아 main이 즉석으로
# _audit/history.md에 append를 못 했고, 그 결과 규정과 달리 T41 파일 기록이 0건이었다
# (2026-09-06 실측). 이 스크립트를 유일한 쓰기 경로로 고정해 형식을 지킨다.
#
# 사용법: bash scripts/t41-append.sh <role> <dim> "<signal>"
#         bash scripts/t41-append.sh --from <subagent_type> --signal "<signal>"   (훅 자동 모드)
#
# 쓰는 쪽 정본: agents/*.md 보고 형식(마지막 text 블록 안 행두 `RESULT: <값>` 한 줄, target=<역할> 선택).
# REJECT 는 `RESULT:`/`STATUS:`/`판정:` 접두형에만 있고 행두 단독형(FAIL|BLOCKED|NEEDS_CONTEXT)에는
# 없다(t41-subagent-stop.sh·agent-spawn-log.sh 의 T41_RX) — A-1 이 항상 `RESULT:` 키를 쓰므로
# 이 비대칭은 무해하다.
set -euo pipefail

usage() {
  echo "사용법: bash scripts/t41-append.sh <role> <dim> \"<signal>\"" >&2
  echo "        bash scripts/t41-append.sh --from <subagent_type> --signal \"<signal>\"" >&2
}

# 역할 정규화(`normalize_role`)와 별칭 표의 정본은 role-alias.sh 다(harness-usage-check.sh 8-pre(옛 8c-2)도 같은 파일을 source 한다 — 2026-10-17).
# shellcheck source=/dev/null
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/role-alias.sh"

# 자동 모드 — 신호를 낸 subagent_type 과 신호 문구로 **약점 주체와 차원**을 정한다.
# 왜 여기 한 곳인가: 두 훅(agent-spawn-log=동기, t41-subagent-stop=비동기)이 각자 판단하면
#   같은 신호가 경로에 따라 다른 축에 쌓인다. 종전에는 둘 다 차원을 `auto` 로 고정해
#   agent-eval §2 차원표가 통째로 무효였고, qa 가 낸 FAIL 을 qa 의 약점으로 적어 규칙과
#   반대로 귀속됐다(09-14 재감사 §3). 매핑 근거는 agent-eval.md §1 신호표다:
#   검증자(qa·reviewer·security)의 FAIL·REJECT 는 만든 쪽(coder)의 구현 정확성 문제이고,
#   BLOCKED·NEEDS_CONTEXT 는 그 일을 맡은 에이전트 자신의 범위 문제다.
if [[ "${1:-}" == "--from" ]]; then
  if [[ $# -ne 4 || "$3" != "--signal" ]]; then
    usage
    exit 2
  fi
  FROM="$2"; SIGNAL="$4"
  # 역할 정규화를 귀속 판단보다 먼저 적용한다(v2 A-2) — 팀원 이름(qa-p1)이 그대로 넘어오면 아래
  # qa·reviewer·security 비교가 실패해 «검증자 FAIL→coder» 규칙이 죽는다(09-26 qa-p1 실사례).
  FROM_NORM="$(normalize_role "${FROM}")"
  [[ -n "${FROM_NORM}" ]] && FROM="${FROM_NORM}"
  # herestring — `printf | grep -q` 는 grep 이 먼저 끝나면 printf 가 SIGPIPE 로 죽고 pipefail 이 그
  # 141 을 결과로 삼아 매치를 놓친다(같은 날 correction-detect 에서 재현된 경합).
  if grep -qE '(BLOCKED|NEEDS_CONTEXT)' <<< "${SIGNAL}"; then
    ROLE="${FROM}"; DIM="범위 준수"
  elif grep -qE '(FAIL|REJECT)' <<< "${SIGNAL}" \
       && [[ "${FROM}" == "qa" || "${FROM}" == "reviewer" || "${FROM}" == "security" ]]; then
    ROLE="coder"; DIM="구현 정확성"
  else
    ROLE="${FROM}"; DIM="결과 실패"
  fi
  # target=<이름> 귀속 (v2 A-5 결정 항목 3): SIGNAL 안에 target= 토큰이 있고 그 이름이 정규화로
  # 유효 역할이면 ROLE 을 그 역할로 덮는다. DIM 은 위에서 정한 값을 그대로 쓴다.
  TARGET=$(grep -oE 'target=[A-Za-z0-9_-]+' <<< "${SIGNAL}" | head -1 | cut -d= -f2- || true)
  if [[ -n "${TARGET}" ]]; then
    # main·general-purpose 는 agents/ 파일이 없어도 유효 역할(아래 존재 검사와 같은 예외).
    # 09-26 실측: 첫 실기록 «target=main» 이 normalize_role 빈 값으로 coder 에 오귀속됐다.
    if [[ "${TARGET}" == "main" || "${TARGET}" == "general-purpose" ]]; then
      ROLE="${TARGET}"
    else
      TARGET_NORM="$(normalize_role "${TARGET}")"
      [[ -n "${TARGET_NORM}" ]] && ROLE="${TARGET_NORM}"
    fi
  fi
elif [[ $# -eq 3 ]]; then
  ROLE="$1"; DIM="$2"; SIGNAL="$3"
else
  usage
  exit 2
fi

CLAUDE_DIR="${HOME}/.claude"
HISTORY="${CLAUDE_DIR}/_audit/history.md"

# main 은 agents/ 에 파일이 없지만 유효한 역할이다. agent-eval.md 약점 축 표에서 「과잉 위임」의
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
    ROLE="general-purpose"
  fi
fi

DIM="$(printf '%s' "${DIM}" | tr '\t\n' '  ')"
SIGNAL="$(printf '%s' "${SIGNAL}" | tr '\t\n' '  ')"

# 10분 중복 억제 (2026-09-14 재감사 §3-b) — 동기 소집은 PostToolUse 와 SubagentStop 이 **둘 다**
# 같은 결과를 보므로 history 에 같은 신호가 두 줄 남고, T41_REPEAT 의 3회 문턱이 부풀었다.
# 억제 장부를 따로 두는 이유: history 줄에는 날짜만 있어 «10분 안»을 줄 자체로는 알 수 없다.
# 장부는 _usage/(gitignore) 에 두고 매 실행마다 10분 밖 항목을 쳐낸다.
#
# 잠금이 필요한 이유 (2026-09-14 재감사 D0): 종전 판은 장부를 «읽고 비우고 다시 쓰기» 했고 잠금이
# 없어 10병렬에서 판정과 기록이 엇갈렸다 — 같은 신호 10개가 history 에 3~4줄을 남겼다(기대 1).
# 그래서 판정 → history append → 장부 기록을 한 임계구역에 넣는다. 장부는 append-only 로 두고
# 가지치기만 같은 잠금 안에서 임시 파일→mv 로 한다(candidates-append.sh 와 같은 flock 방식).
RECENT="${CLAUDE_DIR}/_usage/t41-recent.tsv"
LOCK="${CLAUDE_DIR}/_usage/t41.lock"
KEY="${ROLE}/${DIM}|$(printf '%s' "${SIGNAL}" | cut -c1-60)"
NOW="$(date +%s)"
LINE="- $(date +%Y-%m-%d) T41: ${ROLE}/${DIM} — ${SIGNAL}"
mkdir -p "${CLAUDE_DIR}/_usage" 2>/dev/null || true

record() {
  if [[ -f "${RECENT}" ]]; then
    if awk -F'\t' -v n="${NOW}" -v k="${KEY}" \
        '$1+0 > n-600 && $2==k { f=1 } END { exit f?0:1 }' "${RECENT}"; then
      return 3
    fi
    if ! { awk -F'\t' -v n="${NOW}" '$1+0 > n-600' "${RECENT}" > "${RECENT}.tmp.$$" \
        && mv "${RECENT}.tmp.$$" "${RECENT}"; }; then rm -f "${RECENT}.tmp.$$"; fi
  fi
  printf '%s\n' "${LINE}" >> "${HISTORY}" || return 1
  printf '%s\t%s\n' "${NOW}" "${KEY}" >> "${RECENT}" || return 1
}

LOCKED=0
if command -v flock >/dev/null 2>&1; then
  if ! { exec 9>"${LOCK}" && flock 9; }; then echo "t41-append: 잠금 실패 (${LOCK})" >&2; exit 1; fi
  LOCKED=1
fi
set +e; record; RC=$?; set -e
# 임계구역은 여기까지 — 뒤의 후보 대장 기록은 자기 잠금을 쓴다. 닫을 때 `exec 9>&- 2>/dev/null` 처럼
# 리다이렉션을 덧붙이면 그 2>/dev/null 이 셸 전체에 남아 아래 경고들이 통째로 사라진다(실측).
if [[ "${LOCKED}" -eq 1 ]]; then exec 9>&-; fi
if [[ "${RC}" -eq 3 ]]; then
  echo "t41-append: 같은 신호가 10분 안에 이미 기록됨 — 건너뜀 (${KEY})" >&2
  exit 0
fi
[[ "${RC}" -eq 0 ]] || { echo "t41-append: history 기록 실패 (${HISTORY})" >&2; exit 1; }
printf '%s\n' "${LINE}"

# 후보 대장 기록 (2026-09-14 신설) — 왜: history.md 는 서술형 감사 기록이라 승인 큐·7일 판정
# (CANDIDATES_PENDING)·bench 복귀가 읽지 못한다. T12(correction-detect)·T40(pattern-detect)이
# 쓰는 같은 대장에 T41 도 한 행 남겨야 세 갈래가 한 큐에서 판정된다. 중복 차단·id 연번·헤더 보장은
# candidates-append.sh 잠금 안에서 하고(직접 cp→mv 하던 판은 동시 실행에서 행을 잃었다 — 재감사 B1),
# 실패는 stdout 만 버리고 stderr 로 드러낸다 — 종전엔 cp 실패가 통째로 조용히 삼켜졌다(재감사 §3-c).
SUMMARY="${ROLE}/${DIM}: $(printf '%s' "${SIGNAL}" | cut -c1-60)"
bash "${CLAUDE_DIR}/scripts/candidates-append.sh" T41 "${SUMMARY}" >/dev/null || true
