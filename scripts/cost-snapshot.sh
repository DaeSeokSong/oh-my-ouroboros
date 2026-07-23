#!/usr/bin/env bash
# PreCompact / SessionEnd(reason=clear) 훅용.
# 목적: compaction이 트랜스크립트의 토큰 detail을 요약·소실시키기 "전에", 현재 세션의
#       모델·에이전트별 토큰을 messageId 기준으로 detail ledger에 누적 보존한다.
#       (총액 자체는 coralline total_cost_usd라 detail 유무와 무관하게 항상 정확 —
#        이 스냅샷은 /cost의 "분해 coverage"를 compact 후에도 유지하기 위한 것.)
# 입력: stdin = hook JSON (session_id, transcript_path). non-blocking(항상 exit 0).
# 판단 근거: 훅은 비대화형·단방향(공식 문서) → 스냅샷만 수행, 사용자 상호작용 없음.
PY=$(command -v python3 || command -v python)
[ -z "$PY" ] && exit 0
"$PY" "$HOME/.claude/scripts/cost-breakdown.py" --snapshot 2>/dev/null
exit 0
