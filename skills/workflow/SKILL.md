---
name: workflow
description: "Use when: 복잡한 작업의 Phase 기반 워크플로우 설계 (3단계 이상, teammate 협업, 조건부 분기 포함)."
model: opus
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Workflow
  - Grep
  - Agent
  - AskUserQuestion
  - mcp__mem0__add_memory
  - mcp__mem0__search_memories
  - mcp__mem0__update_memory
  - mcp__mem0__get_memories
---

# Workflow Builder

> **스킬 경계**: 이 스킬은 3단계 이상 복잡한 작업의 Phase 설계 전용. 단순 Confluence 페이지는 `/confluence`, 연구 기록은 `/confluence-research-record` 사용.

복잡한 작업을 실행 전 체계적으로 설계하는 명령입니다.
CLAUDE.md 규칙 12(대량 작업 분할)과 연동하여 Phase 구조로 작업을 분해합니다.

---

## 🔀 두 가지 실행 모드 (MANDATORY — 진입 시 선택)

| 모드 | 메커니즘 | 적합 작업 | 비용 |
|------|---------|----------|------|
| **A. Phase 설계** (기본) | 종이 위 Phase 분해 → Agent subagent 수동 순차/병렬 호출 | 일반 복합 작업(3~7단계), 합의·승인이 핵심 | 낮음 |
| **B. 런타임 Dynamic Workflow** | `Workflow` 도구 — JS로 subagent fan-out/pipeline 자동 오케스트레이션 | 대규모·고가치·다수 독립 항목(대량 마이그레이션·다논문 리뷰·N-후보 토너먼트·대량 audit) | 높음(토큰 多) |

### 모드 B opt-in 조건 (MANDATORY — 공식 가이드)

`Workflow` 도구는 **반드시 사용자 명시 opt-in 후에만** 호출한다:
- 사용자가 `ultracode` 키워드 포함, 또는 "워크플로우 실행/사용"·"fan-out"·"오케스트레이션" 직접 요청, 또는 세션 ultracode 활성, 또는 named/saved 워크플로우 지시.
- opt-in 없으면 **모드 B 금지** → 모드 A로 진행하거나 "워크플로우로 하면 ~게 가능합니다(대략 비용). 진행할까요?" 1줄 제안 후 대기.

### Over-application 가드 (MANDATORY — 공식 안티패턴)

> *"does it really need more compute? most traditional coding tasks do not need a panel of 5 reviewers."*
> 모드 B는 고가치·복합 작업에만. 일반 코딩/단일 파일 수정/단순 질문은 모드 A 또는 직접 처리.

### 모드 B 6대 패턴 + 상세

Classify-and-Act / Fan-out-and-Synthesize / Adversarial Verification / Generate-and-Filter / **Tournament** / Loop Until Done.
→ 패턴·opt-in·안티패턴 방어·script 작성 요점 상세: `rules-lazy/dynamic-workflow.md`.

> 아래 "## 자동 트리거 조건" 이하는 **모드 A(Phase 설계)** 기준이다. 모드 B 선택 시 위 가드 통과 후 `Workflow` 도구로 직접 실행한다.

## 자동 트리거 조건

아래 중 하나라도 해당 시 작업 시작 전 자동 워크플로우 설계 제안:
- teammate 협업이 필요한 복합 작업
- 3단계 이상 순차 작업
- 조건부 분기가 포함된 작업 (Go/NoGo 분기 등)
- 논문/실험/리팩토링 등 장기 작업

## § Mem0 패턴 검색 (워크플로우 설계 전 MANDATORY)

워크플로우 설계 전 Mem0에서 관련 이력 자동 검색:
→ mem0-auto.md T07 참조 (5채널 순차 검색 — discuss와 동일 패턴)

과거 패턴 발견 시: "이전 유사 작업에서 {Phase 구성}으로 진행, {패턴} 적용" → 동일 규칙으로 Phase 설계
사용자 피드백 발견 시: "사용자 선호: {선호 내용}" 반영

## § Mem0 워크플로우 저장 (완료 시)

워크플로우 완료 시 설계 패턴을 Mem0에 저장: → mem0-auto.md T19 참조

---

## 실행 흐름

$ARGUMENTS 를 파싱하여 아래 흐름으로 실행:

1. **인자가 비어있음** → 현재 대화 맥락에서 작업 분석:
   - 최근 사용자 메시지에서 목표/작업 목록 추출
   - 의존 관계 파악 (A 완료 후 B 시작 등)
   - 병렬 가능 작업 식별
2. **인자가 작업 설명** → 해당 작업에 대한 워크플로우 설계
3. 설계 완료 후 사용자 승인 → 승인된 워크플로우대로 실행

## 워크플로우 설계 시 필수 포함 요소

1. **Phase 구분**: 각 단계의 이름, 트리거 조건(항상/조건부), 단계 간 의존 관계
2. **팀 구성**: CLAUDE.md 라우팅 테이블 기반 에이전트 배치
3. **산출물**: 각 Phase의 예상 결과물 명시
4. **분기 조건**: 조건부 Phase의 흐름도 (Go/NoGo 기준 수치 포함)
5. **제약 사항**: 코드 수정 금지 구간, 사용자 승인 필요 시점, 실험 트랙 경계
6. **요약 테이블**: Phase | 트리거 | 핵심 산출물 | 에이전트 | 코드 수정 여부

## 출력 형식

```
Phase A: [이름] ──── 트리거: 항상
  담당: [에이전트/팀]
  산출물: [결과물]
  코드 수정: 없음

Phase B: [이름] ──── 트리거: Phase A 완료 후
  담당: [에이전트/팀]
  산출물: [결과물]
  코드 수정: 있음
          │
     ┌────┴────┐
     ▼         ▼
  [Go 조건]  [NoGo 조건]
     │              │
     ▼              ▼
  Phase C        사용자 에스컬레이션
```

---

| Phase | 트리거 | 핵심 산출물 | 에이전트 | 코드 수정 |
|-------|--------|------------|---------|---------|
| A | 항상 | ... | scout | 없음 |
| B | A 완료 | ... | coder | 있음 |

## § Phase 전환 Gate (MANDATORY — Anthropic 공식)

각 Phase 완료 시 programmatic check 후 다음 Phase 진입:

| Gate 유형 | 형식 | 예시 |
|----------|------|------|
| 수치 기준 | `≥ N%` 또는 `≤ N` | 정확도 ≥ 95%, 에러 ≤ 3건 |
| Boolean | True/False | 빌드 통과, 테스트 PASS |
| 사용자 승인 | "GO/NO-GO" | 설계 합의, 모델 선택 |
| **Rubric (자동 생성)** | N개 항목 모두 PASS | Phase 진입 시 main이 rubric 생성 → 사용자 검토 → Phase 종료 시 채점 |

Gate 실패 시: 해당 Phase 재실행 (최대 N회) 또는 워크플로우 분기.
근거: Anthropic "Building Effective Agents" — Workflow 4패턴 (Prompt chaining, Parallelization, Orchestrator-workers, Evaluator-optimizer).

---

### § Rubric 기반 Gate 흐름 (MANDATORY — Phase 단위 적용)

> **근거**: RubricEM (Li et al. 2026, arxiv 2605.10899) — rubrics as shared interface for policy decomposition + judge feedback. RL 학습 부분은 미적용, rubric 자동 생성·평가 메타 아이디어만 차용.
> **judge 베스트 프랙티스 (MANDATORY)**: rubric 채점은 `~/.claude/rules-lazy/llm-judge-practices.md` 준수 — 항목을 **이진 체크(O/X)**로(아래 작성 원칙과 일치), 평가 중 기준 drift 금지, 근거에 산출물 지점 명시.

#### Phase 진입 직전 (Stage A: rubric 생성)

main이 해당 Phase의 평가 rubric을 **3-5개 항목**으로 자동 생성. 각 항목은 검증 가능한 형태로 작성.

**rubric 항목 작성 원칙**:
- ✅ 검증 가능한 단일 사실 (예: "NaN 0건")
- ✅ Phase 산출물에 명확히 매핑 (예: "split 비율 8:1:1")
- ❌ 모호한 정성 평가 (예: "잘 동작함")
- ❌ 다음 Phase의 영역 침범 (예: 데이터 전처리 Phase에 학습 결과 평가)

**출력 형식**:

```
🎯 Phase {N} ({Phase명}) 진입 — 평가 Rubric 자동 생성

| # | 평가 항목 | 검증 방법 |
|---|---------|---------|
| 1 | {항목1} | {어떻게 PASS 확인} |
| 2 | {항목2} | {어떻게 PASS 확인} |
| 3 | {항목3} | {어떻게 PASS 확인} |

이 rubric으로 진행할까요?
  - Y / 이대로 → Phase 시작
  - 변경 → 항목 추가/제거/수정 후 재확인
```

#### Phase 종료 시 (Stage B: rubric 채점)

Phase 실행 완료 후 main이 각 rubric 항목 채점. **PASS/FAIL boolean**만 사용 (점수화 ❌ — LLM 채점 일관성 한계).

**출력 형식**:

```
✅ Phase {N} 종료 — Rubric 채점

| # | 평가 항목 | 결과 | 근거 |
|---|---------|------|------|
| 1 | {항목1} | PASS | {확인된 사실} |
| 2 | {항목2} | FAIL | {실패 원인 + 위치} |
| 3 | {항목3} | PASS | {확인된 사실} |

종합: 2/3 PASS — 1건 FAIL.
다음 단계 선택:
  1. Phase {N} 재실행 (FAIL 항목 해결)
  2. Phase {N} 결과 수용 + 다음 Phase 진행 (FAIL 명시 기록)
  3. 워크플로우 분기 / 중단
```

#### Mem0 연동

- Phase 진입 시 생성된 rubric → `category=context` 저장 (Phase 별 rubric 이력 보존)
- Phase 종료 시 FAIL 발생 → `category=code_pattern` + `avoidance_rubric` 형식으로 distillation (`rules/mem0-auto.md` T04 참조)
- 다음 동일 Phase 진입 시 → search로 과거 rubric·avoidance 자동 로드 → 새 rubric 보강

#### 생략 조건

- 사용자가 Phase 진입 시 "rubric 생략" / "기본 Gate만" 명시
- 단일 Phase 워크플로우 (Phase 1개) — Gate 자체 불필요
- 사용자 승인 Gate만으로 충분한 정성 작업 (예: "디자인 검토 요청")

---

## § Phase 분할 입도

- Phase 분할 권장 수: 3~7개 (단일 워크플로우 기준)
- 7개 초과 시: 메타-워크플로우로 분리 (Phase A.1, A.2, ...)
- 각 Phase는 단일 산출물·단일 책임 원칙

---

## § 계획→실행 핸드오프 (subagent-driven 차용)

Phase별 task가 독립적이면 **subagent-driven** 실행을 권장:
- task별 fresh subagent(coder) + 2단계 리뷰(qa: spec 준수 → 코드 품질)
- subagent는 세션 히스토리 상속 ❌ — main이 필요한 컨텍스트만 정밀 구성
- 모델 선택: 기계적=haiku/sonnet, 통합·판단=sonnet, 설계·리뷰=opus (model-assignment 정렬)
- coder status 4종(DONE/CONCERNS/NEEDS_CONTEXT/BLOCKED) 핸들링
> worktree 강제·자체 커밋 미적용 — 커밋은 `/commit`, push는 사용자 직접 (우리 git 규칙 우선).

---

## § discuss 사전 추천 (실행 전 자동 체크)

본격 실행 전에 discuss 필요성을 판단하여 사용자에게 추천/비추천을 제시한다.

### 판단 기준

| 조건 | discuss 추천 | 이유 |
|------|-------------|------|
| 아키텍처 변경 수반 | ✅ 추천 | 다관점 검토로 설계 오류 방지 |
| 생물학적 타당성 검증 필요 | ✅ 추천 | researcher 비판적 검토 필수 |
| 하이퍼파라미터 대폭 변경 | ✅ 추천 | 실험 방향 합의 필요 |
| 새로운 데이터셋 도입 | ✅ 추천 | 전처리·분할 전략 합의 |
| 단순 config 미세 조정 | ❌ 비추천 | 토론 비용 > 이점 |
| 이미 합의된 계획 실행 | ❌ 비추천 | 재토론 불필요 |
| 버그 수정/오타 수정 | ❌ 비추천 | 토론 대상 아님 |

### 출력 형식

```
📋 discuss 사전 추천:
| 항목 | 내용 |
|------|------|
| 추천 여부 | ✅ 추천 / ❌ 비추천 |
| 근거 | {해당 조건 1줄} |
| 이유 | {왜 discuss가 필요/불필요한지 1줄} |
| 예상 참여자 | {에이전트 목록} (추천 시) |

discuss를 먼저 진행할까요? (Y/N)
```

- 사용자 Y → `/discuss` 실행 후 본 스킬 재개
- 사용자 N → 바로 실행 진행

## 생략 조건

- 단일 에이전트로 처리 가능한 단순 작업
- 단계가 1개인 작업
- 사용자가 "즉시 진행" 명시 시

## 사용 예시

```
/workflow                              ← 현재 맥락 기반 자동 설계
/workflow 논문 Figure 개선 + 피어리뷰    ← 특정 작업 지정
/workflow 실험 전체 파이프라인           ← 실험 워크플로우 설계
/workflow MCP 도입 + bootstrap 스크립트  ← 여러 단계 설정 작업
```
