---
name: cost-reset
description: "Use when: 누적 cost 집계 초기화 — '/cost-reset'. 총액+detail ledger 삭제. 파괴적 — dry-run 후 삭제는 사용자 직접 실행."
allowed-tools:
  - Bash
---

# /cost-reset — 누적 cost 집계 초기화

statusline이 보여주는 **서버 전체 누적 cost**(coralline `total_cost_usd` ledger)와 `/cost`의 **detail ledger**를 삭제해 0부터 다시 세도록 한다. 개별 세션/트랜스크립트는 건드리지 않는다(비용 집계 파일만).

## 흐름 (파괴적 — 삭제는 사용자 직접 실행, code-execution.md 준수)

1. **dry-run 먼저** (삭제 대상만 표시, read-only — AI 실행 허용):
```bash
python3 ~/.claude/scripts/cost-breakdown.py --reset
```
2. 출력된 삭제 대상(`~/.cache/coralline/cost-ledger`, `~/.cache/claude-cost/detail`)을 사용자에게 보여주고 **명시적 확인**을 받는다.
3. 사용자가 확인하면, 실제 삭제(파괴적·상태변경)는 **AI가 실행하지 않고 사용자에게 실행 명령서를 출력**한다(code-execution.md: 파괴적 명령은 사용자 직접):
```
실행 명령 (사용자 직접 실행):
  python3 ~/.claude/scripts/cost-breakdown.py --reset --yes
```

> **AI가 `--yes`를 직접 실행 금지** — 되돌릴 수 없는 삭제. dry-run(read-only)까지만 AI가 하고, `--yes`는 명령서로 넘겨 사용자가 실행한다.

## 효과·비효과 (정직한 baseline)

- **초기화됨**: 과거 세션들의 누적 집계(coralline ledger 파일들 + detail ledger).
- **⚠️ 완전한 "0"은 아님**: 현재 활성 세션의 `total_cost_usd`는 Claude Code가 소유하고, statusline HUD가 매 렌더마다 그 값을 coralline ledger에 다시 기록한다. 그래서 리셋 후에도 statusline은 0이 아니라 **현 세션 값부터** 재누적된다. `/clear` 이후에도 pre-clear 세션의 coralline 항목은 그 세션 진행 중 이미 기록됐으므로 남는다. **가장 깨끗한 초기화 = `/clear`로 새 세션을 시작한 '직후' `/cost-reset`** (그 시점 새 세션 비용이 최소라 남는 값도 최소).
- **안 건드림**: 세션 트랜스크립트(`projects/*/*.jsonl`) — /cost는 이후에도 라이브 트랜스크립트를 파싱하므로 현재 세션 분해는 계속 보인다.
- clear/compact와의 관계: 평소엔 clear/compact가 누적에 영향 없음(보존). `/cost-reset`은 사용자가 **명시적으로** 과거 누적을 지우고 싶을 때만.

## 관련
- `/cost` — 조회(모델·에이전트별 분해). 상세: `skills/cost/SKILL.md`.
- 누적 보존 메커니즘: PreCompact·SessionEnd(clear) 훅이 `cost-snapshot.sh`로 detail을 ledger에 누적(`scripts/cost-breakdown.py` docstring).
