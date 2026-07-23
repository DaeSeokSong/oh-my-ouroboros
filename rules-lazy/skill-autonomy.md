# 스킬 자율 호출 상세 (agent-routing 보조)

> **로드 시점**: 에이전트가 스킬 자율 호출을 판단하거나, main이 spawn 시 SKILL_DEPTH/특례를 적용할 때 lazy 로드.
> **모(母) 파일**: `~/.claude/rules/agent-routing.md` (always-on — 4-Gate·SKILL_DEPTH 요약)
> 에이전트는 작업 중 필요하다고 판단될 때 4단계 Gate를 통과한 스킬을 자율 호출할 수 있다. 사전에 스킬 체인을 정의하지 않는다 — 에이전트가 맥락에 따라 자율 판단한다.

---

## 4단계 Gate 판단 (순서대로 모두 통과 시 스킬 호출 허용)

| Gate | 조건 | 통과 기준 |
|------|------|-----------|
| Gate 1 | 화이트리스트 | 해당 에이전트의 `agents/*.md` 허용 스킬 목록에 포함되어 있는가 |
| Gate 2 | 필요성 | 스킬 없이 현재 작업을 완료할 수 없거나 품질이 현저히 저하되는가 |
| Gate 3 | 품질 임계값 | 스킬을 쓰지 않으면 일관성·재현성·정확성 기준을 충족할 수 없는가 |
| Gate 4 | 컨텍스트 비용 | 현재 컨텍스트 < 60% — 60% 이상이면 main에게 스킬 호출 위임 |

## 깊이 제한 N=1 (MANDATORY)

- 스킬 실행 중 다른 스킬 재귀 호출 **금지** (/discuss 예외 적용 — 아래 참조)
- 순차 호출은 허용: 스킬 A 완료 후 스킬 B 호출 가능
- spawn prompt에 `SKILL_DEPTH` 카운터 포함:

```
SKILL_DEPTH=0 → 스킬 호출 가능 (4 Gate 통과 시)
SKILL_DEPTH=1 → 스킬 호출 금지 (/discuss 특례 제외)
```

## SKILL_DEPTH 전달 프로토콜 (MANDATORY)

모든 에이전트 spawn 시 prompt 서두에 아래 줄을 포함:

```
[SKILL_DEPTH: N]  ← N=0: 스킬 호출 가능 / N=1: /discuss 외 스킬 호출 금지
```

- main이 에이전트를 직접 spawn 시: `SKILL_DEPTH=0` (기본값)
- 스킬 실행 중 에이전트 spawn 시: `SKILL_DEPTH=1`
- 에이전트는 prompt 서두의 SKILL_DEPTH를 확인 후 whitelist 스킬 호출 가능 여부 판단

## /discuss 재귀 호출 특례 (MANDATORY)

discuss로 소집된 teammate가 다시 `/discuss`를 호출하는 경우 **허용** — 단, 강제 조건 (**소집 실행 주체 전제**: 재귀 /discuss의 하위 에이전트 spawn은 Agent 도구가 있는 teammate·main 컨텍스트에서만 실제 실행된다. Agent 도구 없는 일반 subagent는 재귀 /discuss를 직접 실행할 수 없어 main에 요청으로 반환 — `rules/agent-routing.md` § "소집"의 실행 주체):

| 조건 | 내용 |
|------|------|
| TeamCreate 금지 | 전원 subagent 전용 모드 강제 (teammate spawn 불가) |
| 팀원 수 | ≤ 3명 (토큰 절약) |
| 각 subagent prompt | 핵심 맥락만 — 이전 라운드 요약 200자 이내 |
| 라운드 수 | ≤ 1 (단일 의견 수집 후 종료) |

## 신규 정식 등재 스킬 (Phase A·B 통합 — MANDATORY)

아래 3 스킬은 정식 라우팅 대상이며, 4-Gate 통과 시 해당 에이전트가 자율 호출 가능.

| 스킬 | 호출 주체 | 자율 호출 트리거 |
|------|----------|----------------|
| `superpowers:dispatching-parallel-agents` | coder, scout, searcher, qa | 독립 작업 2+ 감지 시 (공유 state 없음) |
| `/loop` (bundled — interval / dynamic) | main | 학습 모니터링·반복 패턴 감지 + 사용자 비용 결정 후 |
| `ralph-loop:ralph-loop` | qa | 테스트 자동 재시도 — 5-Gate (`rules-lazy/qa-process.md` Ralph 섹션) |

**비용 모델**: 3개 모두 Pro/Max 구독 토큰만 (추가 API 비용 ❌)
**상세 룰**:
- parallel-dispatch: `rules-lazy/parallel-dispatch.md`
- /loop · G-E Loop: `rules-lazy/loop-auto.md`
- ralph-loop: `rules-lazy/qa-process.md` § Ralph Wiggum 루프

---

## 복합 요청 처리 예시

```
"이 모듈 리팩토링하고 Confluence에 기록해"
Step 1: [scout] 모듈 구조 정찰 → 관련 파일 목록
Step 2: [coder] 리팩토링 실행
Step 3: [scout] 호출부/영향 범위 정찰
Step 4: [qa]    검증
Step 5: [gitops] 커밋 (push는 사용자 직접)
Step 6: [docs]  Confluence 업데이트
```
