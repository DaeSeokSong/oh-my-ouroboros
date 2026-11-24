#!/usr/bin/env bash
# audit-history-autocommit.sh — _audit/history.md 에 덧붙은 줄만 저절로 커밋한다 (2026-11-16)
# 부르는 곳: t41-append.sh(백그라운드) · harness-usage-check.sh(동기).
#
# 안전장치(사람 몫을 건드리지 않기 위해 모두 «조용히 건너뜀», 항상 exit 0, push 없음, --no-verify 없음):
#   - 바뀐 게 없음 / index.lock / rebase·merge·cherry-pick 진행 중: 다른 git 작업과 부딪히지 않는다.
#   - 삭제·수정(삭제 수 != 0)이 있음: 덧붙임만 자동, 그 밖은 사람이 본다.
#   - 이 파일의 스테이징분이 워킹 트리와 다름: 누가 손보는 중이므로 건드리지 않는다.
#   - `git commit -- <경로>`(--only): 다른 파일의 스테이징분이 섞이지 않는다.
#   - mkdir 잠금(_usage/audit-autocommit.lock): 동시 실행 방지, 10분 넘은 잠금은 정리.
# 시험용: AUDIT_REPO 로 저장소 경로를 바꾼다(임시 저장소 시험 전용, 격리를 끄는 용도 아님).
# REF: knowledge/harness/code-history/scripts__audit-history-autocommit.sh.md
set -u

REPO="${AUDIT_REPO:-$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)}"
F="_audit/history.md"
LOCKDIR="${REPO}/_usage/audit-autocommit.lock"
LOG="${REPO}/_usage/maintenance.log"

note() { printf '%s audit-autocommit: %s\n' "$(date -Is)" "$1" >> "${LOG}" 2>/dev/null || true; }
g() { git -C "${REPO}" "$@"; }

GD="$(g rev-parse --absolute-git-dir 2>/dev/null)" || exit 0
[ -n "${GD}" ] || exit 0
[ -f "${REPO}/${F}" ] || exit 0
g ls-files --error-unmatch -- "${F}" >/dev/null 2>&1 || exit 0

g diff --quiet HEAD -- "${F}" 2>/dev/null && exit 0

[ -e "${GD}/index.lock" ] && exit 0
for p in rebase-merge rebase-apply MERGE_HEAD CHERRY_PICK_HEAD; do
  [ -e "${GD}/${p}" ] && exit 0
done

NUMSTAT="$(g diff --numstat HEAD -- "${F}" 2>/dev/null)"
DEL="$(printf '%s' "${NUMSTAT}" | awk 'NR==1{print $2}')"
if [ "${DEL}" != "0" ]; then
  note "삭제·수정 있음(del=${DEL:-?}) — 사람 몫이라 건너뜀"
  exit 0
fi

if ! g diff --cached --quiet -- "${F}" 2>/dev/null; then
  g diff --quiet -- "${F}" 2>/dev/null || { note "스테이징분과 워킹 트리가 다름 — 건너뜀"; exit 0; }
fi

mkdir -p "${REPO}/_usage" 2>/dev/null || true
if [ -d "${LOCKDIR}" ] && [ -n "$(find "${LOCKDIR}" -maxdepth 0 -mmin +10 2>/dev/null)" ]; then
  rmdir "${LOCKDIR}" 2>/dev/null || true
fi
mkdir "${LOCKDIR}" 2>/dev/null || exit 0
trap 'rmdir "${LOCKDIR}" 2>/dev/null || true' EXIT

if g commit -q -m "chore: Record audit history lines" -- "${F}" >/dev/null 2>&1; then
  note "history.md 커밋"
else
  note "커밋 실패(훅 거부 등) — 다음 기회에 재시도"
fi
exit 0
