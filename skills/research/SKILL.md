---
name: research
description: "Use when: 심층 멀티소스 리서치·여러 출처 종합 리포트·'심층 리서치/deep research/종합 조사' 요청 시. 빌트인 deep-research vs 하네스 자체 리서치 선택 → 자체 시 citation-verifier 검증 라인 + 선택적 discuss 토론 + 선택적 빌트인 교차비교."
model: opus
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Agent
  - AskUserQuestion
  - mcp__mem0__add_memory
  - mcp__mem0__search_memories
  - mcp__mem0__update_memory
  - mcp__mem0__get_memories
---

# /research — 심층 멀티소스 리서치 오케스트레이터

> **목적**: 다출처 정보를 수집·검증·종합하여 신뢰도 높은 종합 리포트를 산출한다.
> 빌트인 deep-research 엔진과 하네스 자체 체인 중 선택하거나 양쪽 결과를 교차비교한다.

---

## 과용 가드 (MANDATORY — 스킬 진입 직전 체크)

이 스킬은 **진짜 심층 리서치**(다출처 종합 리포트가 필요한 경우)에만 사용한다.

아래 상황에서는 이 스킬 대신 더 적합한 에이전트/스킬로 라우팅한다:

| 요청 유형 | 대신 사용할 것 |
|----------|--------------|
| 단순 검색 / 단발 사실확인 | searcher |
| 독립 작업 2개 이상 병렬 검색 | parallel-dispatch |
| 단일 논문 조회·읽기·분석 | /paper-read |
| 코드 관련 단순 조사 | scout |

위 유형에 해당하면 스킬 실행 중단 후 적합한 에이전트/스킬로 재라우팅한다.

---

## 결정 트리 (AskUserQuestion 단계별 질문 — 조건부 분기)

### Q1. 리서치 엔진 선택

```
AskUserQuestion:
"리서치 엔진을 선택해 주세요.

ⓐ Claude 빌트인 deep-research 사용
   → Claude가 자체 도구로 인터넷을 직접 검색합니다.
   ⚠️ 주의: 빌트인 엔진은 하네스의 citation-verifier, WebSearch-first 정책, untrusted 격리를
            우회합니다. 검증 라인 없이 바로 리포트가 생성됩니다.

ⓑ 하네스 자체 커스터마이즈 리서치 사용
   → searcher 팬아웃 → citation-verifier 검증 → researcher 종합 체인을 실행합니다.
   하네스 검증 정책이 전부 적용됩니다."
```

**ⓐ 선택 시**: Claude 네이티브 웹 검색 도구(WebSearch/WebFetch)로 직접 리서치 → 결과 보고 → **종료** (별도 "deep-research" 스킬을 호출하는 것이 아니라 Claude 기본 검색 능력 사용 — 하네스 검증 라인 우회 주의)

**ⓑ 선택 시**: Q2로 진행 (빌트인 재질문 금지)

---

### Q2. discuss 기능 사용 여부 (ⓑ 선택 후)

```
AskUserQuestion:
"수집된 근거를 바탕으로 discuss 토론을 진행할까요?
(근거 해석·프로젝트 함의 등 多관점 검토가 필요한 경우에 유용합니다)

YES → discuss를 포함한 종합 리서치 진행
NO  → 자체 리서치 체인만 실행 후 종합 리포트 생성"
```

**NO 선택 시**: 자체 리서치 체인 실행 → Q3로

**YES 선택 시**: Q2b로

> **자체 리서치 체인 (NO 경로 또는 Q2b 이후 공통 실행)**:
> 1. parallel-dispatch로 searcher×N 팬아웃 (출처 수집, WebSearch-first 정책 적용)
> 2. citation-verifier 디베이트 (핵심 인용 옹호/회의 → 종합 검증)
> 3. researcher가 인용 달린 종합 리포트 작성

---

### Q2b. discuss를 workflow로 다회 분할할지 여부 (Q2=YES 후)

```
AskUserQuestion:
"discuss 토론을 한 번에 진행할까요, 아니면 주제를 나눠 여러 라운드로 분할할까요?

NO (단일 discuss)  → /discuss 스킬 1회 발동.
                     /discuss가 커스터마이즈·팀 구성·페르소나 등 옵션을 직접 안내합니다.
YES (workflow 분할) → 논제를 N개 순서 라운드로 분해한 뒤 각 라운드마다 /discuss를 순차 발동합니다.
                     ※ 'workflow 다회 분할' 선택은 workflow 오케스트레이션 opt-in입니다."
```

**NO 선택 시**:
- /discuss 스킬 1회 발동 (depth N=1 discuss 예외 적용)
- /discuss가 자체적으로 커스터마이즈/추천 옵션(Step 0.6)을 제시 — 여기서 재구현 금지
- discuss 결과를 자체 리서치 종합에 반영
- Q3로

**YES 선택 시**:
- workflow로 토론 순서를 주제별로 분할 (논제를 N개 순서 라운드로 decompose)
- 각 분할 라운드마다 /discuss 스킬 순차 발동
- Q2c로

> **명시**: workflow는 *토론 순서/주제 분할*만 담당. 실제 토론 실행은 /discuss가 한다.
> **SKILL_DEPTH 주의**: 여기서 '분할'은 /research 내부의 논제 분해이며 **별도 /workflow 스킬 호출이 아니다** — /discuss 순차 발동은 순차 호출 허용 + discuss 특례로 깊이 제한(N=1) 위반 아님.

---

### Q2c. 분할 discuss 보고 시점 (Q2b=YES 후)

```
AskUserQuestion:
"각 discuss 라운드 결과를 언제 보고할까요?

① 라운드별 → 각 /discuss 라운드가 끝날 때마다 결과를 보고합니다.
② 종합 1회  → 모든 라운드가 끝난 뒤 한 번에 종합 보고합니다."
```

선택에 따라 보고 시점을 설정하고 Q3로 진행.

---

### Q3. 빌트인 교차비교 (자체 리서치 완료 후)

```
AskUserQuestion:
"자체 리서치가 완료되었습니다.
추가로 Claude 빌트인 deep-research도 실행하여 결과를 비교할까요?

YES → 빌트인 deep-research 실행 후 자체 결과 vs 빌트인 결과 비교표 + 메타 종합 리포트를 생성합니다.
      (차이·합의·신뢰도 표시 포함)
NO  → 자체 결과로 종료합니다."
```

**YES 선택 시**:
- 빌트인 `deep-research` 스킬 실행
- 비교표 형식:

```markdown
## 자체 리서치 vs 빌트인 비교

| 항목 | 자체 리서치 (하네스) | 빌트인 deep-research | 합의 여부 |
|------|------------------|---------------------|---------|
| {주제 A} | {결론} | {결론} | ✅ 합의 / ⚠️ 차이 |
| {주제 B} | {결론} | {결론} | ✅ 합의 / ⚠️ 차이 |

### 메타 종합
- **합의 항목**: {N개 — 신뢰도 높음}
- **차이 항목**: {N개 — 추가 검증 권장}
- **빌트인 우회 영향**: {citation-verifier 미적용으로 인한 잠재 차이 서술}
```

**NO 선택 시**: 자체 결과로 종료

---

## 핵심 규칙

### discuss vs citation-verifier 층위 구분

| 도구 | 대상 | 역할 |
|------|------|------|
| citation-verifier | 개별 논문 stance | 특정 논문이 주장을 지지/반박/언급하는지 검증 |
| /discuss | 수집 근거의 해석·프로젝트 함의 | 근거를 종합한 결론의 타당성 多관점 토론 |

→ 층위가 다르므로 상호보완적으로 함께 사용 가능.

### 엔진별 정책 적용 범위

| | 하네스 자체 체인 (ⓑ) | 빌트인 deep-research (ⓐ/Q3) |
|-|---------------------|---------------------------|
| citation-verifier | ✅ 적용 | ❌ 우회 |
| WebSearch-first 정책 | ✅ 적용 | ❌ 우회 |
| untrusted 격리 | ✅ 적용 | ❌ 우회 |
| 속도 | 느림 (체인 순차) | 빠름 |

→ 빌트인 엔진(ⓐ 또는 Q3)은 하네스 검증 정책을 우회함을 사용자에게 반드시 명시.

### Mem0 저장 (자체 리서치 종합 완료 시)

자체 리서치 종합 리포트 완성 후 저장 권장:
- T08/T22 호출 (category=paper) → `mem0-auto.md` 참조

### 재귀 호출 규칙

- 이 스킬이 `/discuss`를 호출하는 것은 **discuss 재귀 특례**로 허용 (SKILL_DEPTH=1 상태에서 호출)
- 그 외 스킬 재귀 호출 금지
- `/discuss` 내부에서 다시 `/research`를 호출하는 것은 금지

---

## 자체 리서치 체인 실행 상세

```
parallel-dispatch 팬아웃
  → searcher×N (WebSearch-first, 출처별 수집)
       ↓ 수집 완료
citation-verifier 디베이트
  → 핵심 인용 논문 철회 게이트 (Crossref+OpenAlex)
  → 옹호 에이전트 + 회의 에이전트 병렬 실행
  → 종합: supporting/contrasting/mentioning 비율 보고
       ↓ 검증 완료
researcher 종합 리포트 작성
  → citation-verifier 결과 반영
  → 인용 달린 종합 리포트 (출처 명시, 신뢰도 표시)
       ↓
(Q2=YES 경우) /discuss 토론 반영
  → discuss 결과를 리포트에 통합
```

### 종합 리포트 형식

```markdown
# [리서치 주제] — 종합 리포트

## 개요
- 리서치 일시 / 검색 출처 수 / 핵심 인용 수 / citation-verifier 결과 요약

## 주요 발견

### [주제 A]
{내용} [출처: {소스명}] [신뢰도: ✅ 지지 N / ⚠️ 논쟁 / ❌ 반박]

### [주제 B]
...

## citation-verifier 검증 결과

| 논문/출처 | supporting | contrasting | 철회 여부 |
|----------|-----------|-------------|---------|
| {출처1} | N | N | 없음 |

## discuss 토론 결과 (해당 시)
{합의 사항 / 미해결 쟁점}

## 결론 및 한계
- 핵심 결론
- 추가 검증 권장 항목
```

---

## 사용 예시

```
/research 뇌 가소성과 학습 효율의 관계
/research transformer 어텐션 메커니즘의 최신 연구 동향
/research 강화학습 기반 LLM 정렬 방법론 비교
```
