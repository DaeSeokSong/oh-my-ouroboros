---
name: cost
description: "Use when: 토큰/비용을 모델별·에이전트별로 분해해 보고 싶을 때. '/cost'(현재 세션) / '/cost all'(이 서버 전체 세션 합산). 각 Claude 모델(fable/opus/sonnet/haiku)의 $·비중 + 그 아래 어떤 에이전트가 얼마를 썼는지."
allowed-tools:
  - Bash
  - Read
---

# /cost — 모델·에이전트별 비용 분해

statusline은 총액만 보여준다. 이 스킬은 트랜스크립트(JSONL)를 파싱해 **모델별 $·비중 + 각 모델 하위 에이전트별 사용량**을 렌더한다. read-only(상태 변경 없음).

## 실행

인자에 `all`/`전체`가 있으면 서버 전체, 없으면 현재 세션:

```bash
# 현재 세션 (기본)
python3 ~/.claude/scripts/cost-breakdown.py

# 이 서버 전체 세션 합산
python3 ~/.claude/scripts/cost-breakdown.py --all

# 특정 세션
python3 ~/.claude/scripts/cost-breakdown.py --session <session_id>

# 기계용 JSON
python3 ~/.claude/scripts/cost-breakdown.py --json
```

read-only 파싱이므로 스킬이 직접 실행한다(탐색성 실행).

## 출력 형식 (MANDATORY — 반드시 이 시각화로, 변형·프로즈 대체 금지)

`cost-breakdown.py`의 stdout을 **코드블록에 그대로** 붙인다. 스크립트가 이미 아래 바 차트 형식으로 렌더하므로, **모델당 1줄 = `모델 [10칸 바] $금액 비중% ├ 인라인 에이전트 분해`** 형태가 그대로 나와야 한다. **직접 텍스트로 다시 쓰거나 프로즈 문단으로 대체·요약해서 바를 매몰시키지 말 것.** 요약이 필요하면 차트 아래 **최대 1줄**만.

정확히 이 형태 (예시):
```
  fable-5    ███████░░░ $  687.29  69.4%  ├ (메인 세션) 100%
  opus-4-8   ███░░░░░░░ $  294.34  29.7%  ├ (메인 세션) 100%
  sonnet-5   ░░░░░░░░░░ $    9.34   0.9%  ├ 메인 91% ├ searcher $0.71 ├ citation-verifier $0.16
  haiku-4-5  ░░░░░░░░░░ $    0.05   0.0%  ├ scout $0.05
  합계 $991.03   ⚙️ 외부 codex:codex-rescue(104K tok) (OpenAI 별도)
```
- `/cost all`도 **동일 시각화**(같은 바+인라인 형식). 에이전트 7개+는 top6 + `+N more`.
- 만약 스크립트 출력에 바(█░)가 없으면 그건 버그 — 스크립트를 고쳐야지 프로즈로 우회하지 말 것.
- 시각화가 핵심 산출물이다. 사용자는 "사용량 시각화"를 원함 — 텍스트 재작성 금지.

## 데이터·회계 (근거)

- **모델별 총액** = assistant `message.usage`를 model별 합산. **messageId 전역 dedup 필수** — 트랜스크립트는 같은 메시지 usage를 최대 5회 반복 기록(스트리밍/재기록)하므로 raw 합산 시 3~5배 과다. messageId는 전역 유일이라 `--all`에서 파일 간(resume/fork 복제) 중복도 제거.
- **에이전트별** = 각 Task 결과 `toolUseResult.{agentType, resolvedModel, usage}`(agentId dedup). subagent 토큰은 인라인과 disjoint라 중복 없음. `resolvedModel` 누락 시 `(unknown-model)`로 묶고 ⚠️요금추정 플래그.
- **codex-rescue** 등 외부(OpenAI) 실행은 Anthropic 청구가 아니라 '외부'로 분리(토큰만, $ 미환산).
- **$ 환산**: `config/model-pricing.json` 요금표 × 토큰. cache read=90% 할인 요율, cache write=usage에 5m/1h 분리가 있으면 각 요율·없으면 5m 가정. 요금표에 없는 모델은 `_fallback`(부정확, 플래그됨). **API 정가 환산치이며 구독 실지불·할인·장문 프리미엄 미반영.**
- **총액(권위) = coralline `total_cost_usd`**: `/cost all`의 grand total = 전 세션 합 = **statusline이 표시하는 값과 일치**(coralline seg_cost가 ledger 전체를 합산 표시). `/cost`(세션)는 **이 세션 값**만 — statusline 표시값(전 세션 합)과 다를 수 있으니 전체는 `/cost all`. Claude Code 산정값이라 **clear/compact에 안전**(세션 파일 보존, compact는 같은 세션 유지). 토큰 분해 합계는 `coverage%`로 병기.
- **compaction 대비 detail 보존**: `PreCompact`·`SessionEnd(clear)` 훅이 `cost-snapshot.sh`로 compaction 직전 모델·에이전트 detail을 `~/.cache/claude-cost/detail/<session>.json`에 messageId 기준 누적. /cost는 이 ledger(누적) ∪ 라이브 트랜스크립트로 분해를 복원 → compact돼도 coverage 유지(단 이 기능 도입 *전* compact로 이미 소실된 detail은 복구 불가).
- **누적 초기화**: `/cost-reset`(스킬) — statusline 총액 + detail ledger를 0부터. 파괴적, 확인 게이트.
- **clear 리마인더**: `/clear` 시 새 세션에서 `cost-clear-note.sh`가 "누적 보존됨 + /cost-reset 안내"를 주입(비차단). ⚠️ 훅은 인터랙티브 선택지 불가(공식 문서 확인) — 그래서 리마인더 + 스킬로 제어.

## 유지보수

- **요금 출처(공식)**: https://platform.claude.com/docs/ko/about-claude/pricing — 2026-07-18 전 항목 대조 일치 확인. 요금 변동 시 이 페이지로 재확인 후 `config/model-pricing.json`만 갱신.
- 신규 모델 추가 시 동 파일 `models`에 항목 추가(없으면 `_fallback` + ⚠️요금추정 플래그).
- **고속 모드**: `usage.speed=='fast'`면 Opus를 `(fast)` 요금(4.8=$10/$50, 4.7=$30/$150)으로 자동 분리 과금 — 별도 모델 행으로 표시.
- 파서 회계 로직 상세는 `scripts/cost-breakdown.py` docstring, 트랜스크립트 회계 근거는 `knowledge/harness/transcript-cost-accounting.md` 참조.

## statusline과의 관계

statusline(claudenews-hud)은 총액만 유지 — 상세는 이 스킬로만(2026-07-18 사용자 결정: statusline 안 늘림). 크로스 세션 누적이 필요하면 향후 Stop 훅이 세션 종료 시 per-agent 집계를 롤업 ledger로 append하는 확장 여지 있음(현재는 on-demand 파싱).
