#!/usr/bin/env bash
# SessionStart 훅: cwd 프로젝트에 graphify-out/이 있으면 리마인더 1줄 주입.
#
# 왜(판단 근거): code-graph.md §2 "구조 질문은 graphify query 우선" 룰이 있음에도
#   실측(2026-07-31) 최근 14일 한 프로젝트 세션 182개 중 graphify query 사용 1개 —
#   구축-미사용 rot(#5). lazy 룰은 로드 안 되면 없는 룰이므로, 세션 시작 시
#   런타임 신호를 주입해 발동율을 올린다 (사용자 결정: 트리거 강화).
# 겸용: graph.json보다 새 소스가 있으면 stale 경고 — post-commit 훅 조용한 실패의
#   조기 감지 장치 (그 프로젝트의 8일 정체 재발 방지).
set -u
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
G="$ROOT/graphify-out/graph.json"
[ -f "$G" ] || exit 0
# 하네스(~/.claude)는 나이틀리 LLM 파이프라인 전용 — 수동 update 권고 자체가 오염 벡터
# (2026-07-31 실사고: AST-only update가 md semantic 중복 병합으로 그래프 2배 오염).
# 물리 경로 비교(pwd -P) — 심링크 별칭 우회 방지 (knowledge/harness/path-guard-symlink-bypass.md)
if [ "$(cd "$ROOT" 2>/dev/null && pwd -P)" = "$(cd "$HOME/.claude" 2>/dev/null && pwd -P)" ]; then
  echo "📊 graphify-out 존재: 구조·연관 질문은 'graphify query' 우선 (rules-lazy/code-graph.md §2) ⚠ 하네스 그래프는 나이틀리 자동 갱신 전용 — 수동 'graphify update' 금지(오염)"
  exit 0
fi
STALE=""
for d in src lib scripts; do
  [ -d "$ROOT/$d" ] || continue
  N=$(find "$ROOT/$d" -name '*.py' -newer "$G" 2>/dev/null | wc -l)
  if [ "${N:-0}" -gt 0 ]; then
    STALE=" ⚠ ${d}/ 소스 ${N}개가 그래프보다 최신(stale) — 'graphify update .' 실행 권장"
    break
  fi
done
echo "📊 graphify-out 존재: 구조·연관·영향범위 질문은 Grep 전에 'graphify query' 우선 (rules-lazy/code-graph.md §2)${STALE}"
exit 0
