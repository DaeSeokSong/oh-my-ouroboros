#!/usr/bin/env bash
# role-alias.sh — 역할 정규화 순수 함수 `normalize_role` (2026-10-17, t41-append.sh 에서 분리)
#
# 왜 분리했나: T41 역할 이름을 t41-append.sh(기록)와 harness-usage-check.sh 8-pre(옛 8c-2, 효과 집계)가 서로 다르게 읽으면
#   같은 역할이 기록은 `security`, 소집 로그는 `sec-g1` 로 갈라져 n_spawn 이 0 으로 샌다. 정본을 이 파일 한 곳에 두고 둘 다 source 한다.
# 사용: `. scripts/role-alias.sh; normalize_role <이름>` → agents/<이름>.md 에 해당하는 역할명을 stdout 으로(없으면 빈 문자열).
# 부수효과 없음: 옵션(set -e 등)을 바꾸지 않고, 파일을 쓰지 않고, 읽기는 ${HOME}/.claude/agents 목록뿐이다.
#
# 역할 정규화 (v2 A-2, 2026-09-26): agents/*.md 이름과 같거나 그 이름 + `-` 로 시작하는 것 가운데
# 가장 긴 것을 반환한다(qa-p1→qa, coder-1-2→coder, citation-verifier-1→citation-verifier). 매치가
# 없으면 빈 문자열 — 상류 40자 절단 값을 그대로 쓰고 재-sanitize 하지 않는다.
# 구분자는 `-` 와 `_` 둘 다 인정한다(2026-10-17 G2: `qa_v_rep` 이 general-purpose 로 새던 10-06 실사례).
# 역할 별칭 표 (2026-10-17, 정본은 여기 한 곳): 줄임말 접두를 agents/ 이름으로 바꾼다
# (sec-g1→security, citation-1→citation-verifier). 접두 뒤는 끝이거나 `-`·`_`·숫자일 때만 인정하고 표 밖 이름은 그대로 둔다.
# 묶음 접두 (2026-11-12): `unit<숫자>-` · `unit<숫자>_` 는 떼고 나머지를 같은 규칙으로 푼다(unit5-security→security, unit3-qa-2→qa).
#   검증자의 FAIL 이 general-purpose 로 오귀속되던 T41-20261112-02·04 실사례. 숫자가 없거나 구분자가 없으면(unitx-qa·unit5qa) 그대로 둔다.
normalize_role() {
  local raw="$1" dir="${HOME}/.claude/agents" best="" bestlen=0 f base pair rest
  if [[ "${raw}" == unit[0-9]* ]]; then
    rest="${raw#unit}"
    while [[ "${rest}" == [0-9]* ]]; do rest="${rest#[0-9]}"; done
    [[ "${rest}" == [-_]?* ]] && raw="${rest#[-_]}"
  fi
  for pair in sec:security security:security qa:qa coder:coder scout:scout searcher:searcher planner:planner researcher:researcher \
      reviewer:reviewer docs:docs gitops:gitops tutor:tutor citation:citation-verifier; do
    if [[ "${raw}" == "${pair%%:*}" || "${raw}" == "${pair%%:*}"[-_0-9]* ]]; then raw="${pair#*:}"; break; fi
  done
  for f in "${dir}"/*.md; do
    [[ -e "${f}" ]] || continue
    base="${f##*/}"; base="${base%.md}"
    if [[ "${raw}" == "${base}" || "${raw}" == "${base}"-* || "${raw}" == "${base}"_* ]] && (( ${#base} > bestlen )); then
      best="${base}"; bestlen=${#base}
    fi
  done
  printf '%s' "${best}"
}
