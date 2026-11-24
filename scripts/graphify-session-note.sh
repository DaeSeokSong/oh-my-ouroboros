#!/usr/bin/env bash
# SessionStart 훅: cwd 프로젝트에 graphify-out/이 있으면 리마인더 1줄 주입.
#   graph.json보다 새 소스가 있으면 stale 경고를 붙인다. 종료 코드는 늘 0.
# REF: knowledge/harness/code-history/scripts__graphify-session-note.sh.md
set -u
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
G="$ROOT/graphify-out/graph.json"
[ -f "$G" ] || exit 0
# WHY: 하네스(~/.claude) 그래프는 나이틀리 LLM 파이프라인 전용이라 수동 update 를 권하지 않는다(2026-07-31: AST-only update 가 그래프를 2배로 오염).
# NEVER: pwd -P 없이 비교하지 않는다. 심링크 별칭으로 우회된다(knowledge/harness/path-guard-symlink-bypass.md).
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
