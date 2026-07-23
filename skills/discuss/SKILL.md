---
name: discuss
description: "Use when: 아키텍처 토론, 타당성 검증, 비교 분석, '토론', '검토', 'teammate' 소집. 주제 세분화 + 에이전트 최적 배정 + 내부 만장일치 달성까지 지속. Subagent/Teammate 하이브리드 — 컨텍스트 조건에 따라 자동 결정."
model: opus
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Agent
  - TeamCreate
  - TeamDelete
  - SendMessage
  - AskUserQuestion
  - mcp__mem0__add_memory
  - mcp__mem0__search_memories
  - mcp__mem0__update_memory
  - mcp__mem0__get_memories
---

# Multi-Perspective Discussion

주제 자동 세분화, 에이전트 최적 배정, 내부 만장일치 달성까지 내부 진행.
**계층적 팀 구조** + **Subagent/Teammate 하이브리드** — 역할과 컨텍스트 조건에 따라 실행 방식 자동 결정.

## 자동 트리거 조건

- "토론", "검토", "타당성 검증", "비판적으로", "비교 분석" 키워드
- 구현 방법이 2개 이상 존재하는 경우
- 새로운 아키텍처 설계/변경 요청 시

---

## § 계층적 팀 구조 (MANDATORY)

**팀장 (Leader)**: teammate로 소집. 담당 세분 항목 분석, 조수 소집, 의견 종합 후 main에 보고.
**조수 (Assistant)**: 팀장이 직접 소집하는 하위 에이전트.

| 조수 유형 | 소집 도구 | 사용 조건 |
|----------|----------|---------|
| **subagent** | Agent(subagent_type=...) | 짧은 조사, 단방향 결과 반환 |
| **teammate** | Agent(team_name=..., name=...) | 조수 간 상호 참조·반복 피드백 필요 시 |

**조수 모델 제한 (MANDATORY)**: 팀장이 **직접 소집하는 조수(assistant)**만 팀장보다 하위 모델. 이는 팀장 하위의 조수에만 적용되며, **동급 팀원(peer 팀원 — 예: 필수 researcher(opus))에는 적용되지 않는다** (팀원은 팀장의 조수가 아니라 병렬 참여자 — 2026-07-17 Codex C5 명확화). 즉 opus planner 팀장 + opus researcher 팀원은 모순이 아니다.

| 팀장 모델 | 허용 조수 모델 |
|----------|-------------|
| opus | sonnet, haiku |
| sonnet | haiku |
| haiku | 조수 소집 금지 |

---

## § 필수 비판팀 — researcher (MANDATORY)

모든 discuss에 researcher 참여. 역할 표기만 다름.
- **연구 discuss**: 비판적 연구 검토자 (기본 역할)
- **비연구 discuss**: `critic(researcher)` 표기. spawn prompt 서두에 포함:

```
researcher는 비판적 연구 검토자이지만, 본 discuss에서는 **비판적 검토자**로 참여합니다.
수학적 결함, 논리적 모순, 실현 불가능한 가정을 집중적으로 지적하십시오.
```

**전 팀 토론 규칙 (MANDATORY)**: 경청(상대 의견 끝까지 인용) → 수용(타당한 지적은 입장 수정) → 재반박(수용 불가 시 구체 근거) → 합의(타협안 또는 데드락 선언)

---

## § _workspace 하이브리드 데이터 전달 (MANDATORY)

| 데이터 크기 | 전달 방식 |
|-----------|---------|
| 200자 이하 | SendMessage 직접 전달 |
| 200자 초과 | `_workspace/{팀원명}_{주제}.md` 저장 후 경로만 전달 |

> 200자 기준은 **teammate 간 SendMessage** 전용 — subagent→main 반환은 100자 기준 별도 적용 (`rules-lazy/agent-routing-mcp.md` § 적재 기준 강화).

**경로 규칙**:
```
${LONG_TERM_ROOT:-~/workspace/_data/workspaces/user/.claude/long-term}/{project}/meetings/{year}/{month}/{date}/{회의_제목}/_workspace/
```

---

## § 회의록 + _workspace 통합 경로 (MANDATORY)

```
${LONG_TERM_ROOT:-~/workspace/_data/workspaces/user/.claude/long-term}/{project}/meetings/{year}/{month}/{date}/{회의_제목}/
├── 회의록.md
└── _workspace/
    └── {팀원명}_{주제}.md
```

- `{project}`: cwd 기반 프로젝트명
- `{year}/{month}/{date}`: 회의 날짜
- `{회의_제목}`: 주제 snake_case 변환

---

## § 회의록 형식 (MANDATORY)

5W1H 헤더 + 채팅 로그 형식.

```markdown
# {회의 제목}

## Who · When · Where · What · Why · How

| 항목 | 내용 |
|------|------|
| **Who** | {팀원명(역할), ...} |
| **When** | {YYYY-MM-DD} |
| **Where** | {회의록 저장 경로} |
| **What** | {주제 1줄} |
| **Why** | {배경 1~2줄} |
| **How** | {팀 구성 요약} |

---

## 토론 로그

### Round 1

> **planner**: {설계안 + 근거 1~3문장}
> **researcher**: {반박 + 근거}
> **coder**: {구현 관점}

**Round 1 결론**: {합의 / 미합의 + 쟁점}

### Round 2
...

---

## 최종 합의
- {합의 사항}

## 미해결 사항
- {있으면 기술, 없으면 "없음"}

## _workspace 참조
- [{팀원}_{주제}.md](_workspace/{팀원}_{주제}.md)
```

**작성 규칙**: 각 발언은 `> **에이전트명**: {내용}` 형식. 발언 순서: 제안자→비판자→검증자→탐색자. subagent 결과도 동일 형식.

---

## § 에이전트 실행 방식 — Subagent vs Teammate

| 페르소나 | 실제 에이전트 | 기본 방식 | 이유 |
|----------|--------------|-----------|------|
| A (중재자) | main | — | 항상 main 직접 담당 |
| B (현황분석) | scout + coder 관점 | **subagent** | 코드베이스 조회·보고, 단방향 |
| C (솔루션설계) | planner | **teammate** | 설계 제안→비판 수용→재제안 필요 |
| D (비판적검토) | researcher / critic(researcher) | **teammate** | 반론→즉각 확인→재반론 필요 |
| E (코드검증) | qa | **teammate** | 구현 오류 지적·질문·반론 필요 |
| F (근거수집) | searcher | **subagent** | 외부 자료 수집·보고, 단방향 |

> B, F는 항상 subagent. C, D, E는 역할별 개별 판단 (아래 § 할당 기준 적용).

---

## § Teammate vs Subagent 할당 기준 (MANDATORY)

### 사전 조건 (전원 subagent 강제)

```
조건 0. SKILL_DEPTH=1 → TeamCreate 금지 → 전원 subagent 강제
         (팀원 ≤3, 각 prompt 핵심 맥락 200자 이내, 라운드 ≤1)
조건 1. 컨텍스트 < 50% 미충족 → 전원 subagent 강제 (50% 사전 게이트)
         70%+ 도달 시 런타임 자동 전환 — § Teammate 런타임 자동 전환 참조 (별도 런타임 게이트)
조건 2. discuss-state.md 초기화 완료 확인
```

### 역할별 개별 판단 (MANDATORY)

| 기준 | teammate | subagent |
|------|----------|----------|
| 상호작용 | 다른 팀원 의견 보고 반박/보완 필요 | 독립적 의견 제출이면 충분 |
| 라운드 | 2회+ 왕복 예상 | 1회 의견 수집으로 끝남 |
| 역할 관계 | 대립 구도 (찬성 vs 비판) | 병렬 분석 (각자 다른 관점) |
| 데이터 의존 | A 분석 결과를 B가 검증해야 함 | 각자 독립 데이터로 분석 |

**판단 규칙**: 4가지 중 2개 이상 teammate 해당 → teammate / 그 외 → subagent

**배정 예시**:
```
아키텍처 토론:
  planner (teammate)    — 설계 제안 후 반박 수신·수정안 재제출 [상호작용✓ 라운드✓ 대립✓]
  researcher (teammate) — planner에 반박, 타당성 검증 [상호작용✓ 대립✓ 데이터의존✓]
  coder (subagent)      — 구현 난이도 독립 평가 [1회 보고]
  scout (subagent)      — 기존 코드 영향 범위 탐색 [1회 보고]
```

**팀 구성 보고 시 배정 근거 포함 (MANDATORY)**:

```
| 팀원 | 역할 | 실행 방식 | 근거 |
|------|------|----------|------|
| planner | 설계 제안 | teammate | 상호작용✓ 라운드✓ 대립✓ (3/4) |
| researcher | 비판적 검토 | teammate | 상호작용✓ 대립✓ 데이터의존✓ (3/4) |
| coder | 구현 평가 | subagent | 1회 독립 보고 (0/4) |
```

---

## § Teammate 런타임 자동 전환 (teammate → subagent)

```
트리거:
  1. SendMessage 응답 없음 (2회 연속) → 해당 teammate를 subagent로 대체
     → discuss-state.md 내용을 subagent prompt에 전체 주입
  2. TeamCreate / teammate spawn 실패 → 전원 subagent 전환
  3. 라운드 5회 초과 합의 미도달 → 쟁점 목록과 함께 main에 에스컬레이션

전환 시 공통: discuss-state.md 저장 확인 → subagent Spawn Prompt 템플릿 사용 → 사용자 1줄 보고
```

---

## § compact 금지 + 종료 순서 (MANDATORY)

**discuss 진행 중 compact 절대 금지** — `context-management.md` § "/discuss 활성 중 compaction 주의" 참조.
Round 도중 compaction 발생 시 → discuss-state.md에 저장된 마지막 Round부터 재시작.

**종료 순서 (MANDATORY)**:

```
1. 회의록 작성 (위 § 회의록 형식 그대로)
   1.5. Mem0 결과 저장 (MANDATORY): → mem0-auto.md T06 참조
        Fallback: 회의록 "## 최종 합의" 섹션 기록
2. SendMessage(target="all", message="discuss 완료 — clear")
3. bash ~/.claude/scripts/tmux-panels.sh purge
4. TeamDelete 실행
```

---

## 핵심 아키텍처 원칙

**상태 파일** — **매 SendMessage 교환 직후 즉시 append**:
`~/.claude/teams/{team_name}/discuss-state.md`

- SendMessage 1건 = discuss-state.md append 1회 (Round 완료까지 대기 금지)
- Round 완료 시 `### Round N 종료` 구분자 + 합의 여부 추가
- 세션 재개 시 마지막 append 지점부터 이어서 진행

**Subagent 모드**: Agent 도구 + subagent_type. 이전 라운드 기록 전체를 prompt에 주입. 반환 후 즉시 종료.
**Teammate 모드**: TeamCreate → Agent(team_name, name). 각 Round 완료 시 discuss-state.md 저장. agent-routing.md § Teammate 중복 생성 방지 준수.

---

## 실행 흐름

$ARGUMENTS 파싱 후 순서대로:

1. **기존 팀 확인 (MANDATORY)**: `~/.claude/teams/` 하위 활성 팀 확인
   - 동일 목적 팀 + state 있음 → 이어서 진행 여부 질문
   - 동일 목적 팀 (state 없음) → 재활용 (TeamCreate 금지)
   - 다른 목적 팀 → TeamDelete 후 새 팀 생성
   - 활성 팀 없음 → 2번 진행

1.5. **교차 검증 필요 여부 확인**: 논문·연구 근거 관련 시:
   ```
   논문 교차 검증을 먼저 진행할까요? (Y/N)
   ```
   - Y: `/paper-read --consensus` 실행 → citation-verifier 교차 검증 보강 → 결과를 팀원 prompt에 주입
   - N: 바로 2번 진행
   - 자동 판단: "논문/연구/근거/타당성/검증/선행 연구" 키워드 포함 시 질문 표시
   - 생략 조건: 순수 코드/아키텍처 토론, 사용자 "논문 없이" 명시

1.6. **Mem0 크로스 채널 사전 검색 (MANDATORY)**: → mem0-auto.md T07 참조
   결과를 "## 사전 맥락"으로 정리 → 팀장 spawn prompt 주입.
   Mem0 불가 시: Grep(long-term/ + short-term/) 결과로 대체.

2. **주제 세분화** (§ Step 0.5 참조)
2.5. **커스터마이즈 선택지** (§ Step 0.6 참조) — 토론 모드 / 팀원 구성 / 페르소나 3단계
3. **에이전트 배정** — researcher/critic(researcher) 필수 포함 확인 + Step 0.6 결과 반영
4. **실행 방식 결정** (§ Teammate vs Subagent 할당 기준) — 역할별 개별 판단
5. **팀 구성 보고** 후 사용자 승인 (Step 0.6 통합 결과 출력)
6. `~/.claude/teams/{team_name}/discuss-state.md` 초기화
7. 회의록 디렉토리 + `_workspace/` 생성
8. **Round 1 실행** (§ 토론 프로세스 참조)
9. 만장일치 → **§ 종료 순서 실행** / 데드락 → 사용자 에스컬레이션

---

## § Step 0.5 — 주제 세분화 (MANDATORY)

| 관점 | 세분화 예시 |
|------|------------|
| 이론/수식 | 수학적 근거, 수렴 조건, 복잡도 |
| 구현 | 코드 변경 범위, 의존성, 인터페이스 |
| 성능/효율 | 연산량, 메모리, 속도 |
| 실험 근거 | 논문 결과 비교, ablation |
| 생물학적 타당성 | 신경과학 메커니즘 대응 여부 |
| 코드베이스 현황 | 기존 코드 적용성, 충돌 위험 |
| 리스크 | 실패 시나리오, 롤백 가능성 |

출력 형식:
```
📌 주제 세분화:
1. [항목 A] — 담당: {에이전트명} — 핵심 질문: ...
2. [항목 B] — 담당: {에이전트명} — 핵심 질문: ...

이 구성으로 진행할까요?
```

---

## § Step 0.6 — 추천안 우선 + 선택적 커스터마이즈 (MANDATORY)

> **목적**: Step 0.5 완료 직후, 추천안을 자동 생성·표시한 뒤 사용자가 "이대로 진행" 또는 "커스터마이즈" 분기 선택. 커스터마이즈 선택 시 에이전트 풀 → 팀 구성 → 페르소나 → 비판 모드 4단계 순차 진행.
> **적용 시점**: Step 0.5(주제 세분화) 완료 직후, § 에이전트 배정 진입 직전. **단축 명령으로 생략 불가** — 항상 실행.
> **단축 응답**: 사용자가 추천안을 본 후 "이대로" / "Y" / "추천대로" 응답 시 추천안 즉시 적용. 4단계 진입은 명시적 "커스터마이즈" 응답 시만.

---

### [Stage 0] 추천안 자동 생성 + 표시 (MANDATORY — 항상 실행)

Step 0.5 주제 세분화 결과를 기반으로 main이 추천안을 자동 생성한다. 이 단계는 사용자 입력 없이 즉시 실행.

#### 추천안 자동 생성 규칙

| 차원 | 추천 규칙 |
|------|---------|
| **에이전트 풀** | 주제 세분화 담당 에이전트 + researcher 필수 (이미 포함) — 자동 추가 ❌ |
| **팀 구성** | 단일 팀 (`main`), 팀장은 leader 우선순위 (planner > researcher > coder)에 따라 자동 지정 |
| **페르소나** | `~/.claude/rules-lazy/agent-personas.md § 자동 할당 규칙` 적용 (기본 균형 페르소나 + 1명 이질 페르소나 다양성 보장) |
| **비판 모드** | 전원 `standard` + 1명 `devil's-advocate` 자동 할당 (팀원 ≥ 3명일 때, devil's advocate는 researcher 우선) |

#### 추천안 출력 형식 (MANDATORY)

```
🎯 Step 0.6 — 추천 토론 구성 (자동 생성)

| 팀     | 에이전트   | 역할 | 페르소나                | 비판 모드           |
|--------|-----------|------|------------------------|-------------------|
| main   | {팀장}    | 팀장 | {persona_id}           | {critique_mode}   |
| main   | {팀원1}   | 팀원 | {persona_id}           | {critique_mode}   |
| main   | {팀원2}   | 팀원 | {persona_id}           | devil's-advocate  |

이대로 진행할까요?
  - **Y / "이대로" / "추천대로"** → 추천안 그대로 토론 시작
  - **"커스터마이즈" / "수정"** → 4단계 순차 커스터마이즈 진입
  - **특정 항목만 변경** (예: "researcher 페르소나만 변경") → 해당 단계만 분기 진입
```

#### 분기 처리

| 사용자 응답 | 다음 단계 |
|------------|---------|
| `Y` / `이대로` / `추천대로` / `진행` | 추천안 그대로 적용 → 토론 시작 (§ 토론 프로세스로 이동, 4단계 건너뜀) |
| `커스터마이즈` / `수정` / `변경` | [1/4]부터 순차 진행 |
| `{에이전트} 페르소나 변경` | [3/4] 해당 에이전트 단계만 분기 진입 후 확정 |
| `{에이전트} 비판 모드 변경` | [4/4] 해당 에이전트 단계만 분기 진입 후 확정 |
| `팀 구성 변경` | [2/4]부터 진행 |
| `에이전트 추가` / `제거` | [1/4]부터 진행 |

> Stage 0 추천안 출력은 **단축 명령으로 생략 불가**. 토론 시작 전 사용자가 반드시 한 번은 추천안을 확인해야 한다.

---

### 4단계 커스터마이즈 (사용자가 "커스터마이즈" 또는 특정 단계 변경 응답 시만 진행)

---

#### [1/4] 에이전트 풀 결정

기본 추천 에이전트는 Step 0.5 주제 세분화 결과 기반 자동 산출. 사용자는 추가 에이전트 명시 가능.

```
📋 [1/4] 에이전트 풀 결정

기본 추천 에이전트 (주제 세분화 기반):
- {추천1}    [{담당 항목}]
- {추천2}    [{담당 항목}, 필수 비판팀]
- {추천3}    [{담당 항목}]

가용한 추가 에이전트:
- designer  (Figure·다이어그램)
- docs      (문서화)
- qa        (검증·테스트)
- searcher  (인터넷 검색)
- scout     (코드베이스 정찰)
- gitops    (git 작업)

추가할 에이전트가 있나요? (이름 나열 / "없음" / "추천대로")
```

응답 변환:
- "없음" / "추천대로" → 기본 추천 그대로 사용
- 에이전트 이름 나열 → 추천 + 추가 에이전트로 확장된 풀 구성

> **제약**: researcher(또는 critic-researcher)는 § 필수 비판팀 (MANDATORY)에 의거 **항상 포함**, 제거 불가.

---

#### [2/4] 팀 구성 방식

에이전트 풀이 확정되면 단일 팀 / 복수 팀 / 단일 팀 + 팀장 지정 중 선택.

```
🏛️ [2/4] 팀 구성 방식

옵션:
1. 단일 팀 (기본) — 전원 하나의 팀, 팀장은 main이 자동 지정
2. 복수 팀 — 주제별 팀 분할, 팀장·팀원 직접 지정
3. 단일 팀 + 팀장 사용자 지정

선택?
```

##### 옵션 2 (복수 팀) 진행 절차

옵션 2 선택 시 아래 절차로 순차 진행:

```
→ 몇 개 팀으로 나눌까요?
[사용자] N

→ Team 1 이름?
[사용자] {팀명1}
→ Team 1 ({팀명1}) 팀장 선택:
  1) {에이전트1}  2) {에이전트2}  ...  N) {에이전트N}
[사용자] {번호} → 선택된 에이전트가 팀장
→ Team 1 ({팀명1}) 팀원 선택 (multi-select, 남은 에이전트 중):
  1) ...  2) ...
[사용자] {번호 나열}

→ Team 2 이름?
... (동일하게 N개 팀 모두 진행)
```

##### 팀 구성 확정 출력 (MANDATORY)

```
✅ 팀 구성 확정:
| 팀     | 팀장       | 팀원        |
|--------|-----------|------------|
| {팀1}  | {팀장1}    | {팀원1...}  |
| {팀2}  | {팀장2}    | {팀원2...}  |
```

##### 옵션 1·3 처리

- 옵션 1: 자동 팀명 (예: `main`), 팀장은 leader 우선순위 따라 자동 지정 (planner > researcher > coder)
- 옵션 3: 단일 팀이지만 팀장만 사용자 선택 후 자동 출력

---

#### [3/4] 페르소나 개별 지정 (각 에이전트 순회)

팀 구성이 확정되면 **에이전트 한 명씩 돌아가며** 페르소나 선택지 제시. 자동 할당 옵션 없음 — 모두 직접 체크.

```
🎨 [3/4] 페르소나 개별 지정

▶ {에이전트1} ({팀명} {역할})
   1) {agent-personas.md의 페르소나1}  — {강령 요약}
   2) {agent-personas.md의 페르소나2}  — {강령 요약}
   3) {agent-personas.md의 페르소나3}  — {강령 요약}

   선택?
[사용자] {번호}
  → {persona_id} 적용

▶ {에이전트2} ({팀명} {역할})
... (동일하게 모든 에이전트 순회)
```

> 페르소나 옵션 본문(강령·우선순위·산출물 스타일)은 `~/.claude/rules-lazy/agent-personas.md`에서 자동 로드하여 출력.
> 단축: 사용자가 "기본 페르소나" 또는 "자동" 명시 시 — `agent-personas.md § 자동 할당 규칙`에 따라 일괄 적용.

---

#### [4/4] 비판 모드 개별 지정 (각 에이전트 순회)

페르소나 지정 완료 후 **다시 에이전트 한 명씩 돌아가며** 비판 모드 4종 중 선택.

```
⚖️ [4/4] 비판 모드 — 각 에이전트 순회 지정

▶ {에이전트1} ({팀명} {역할})
   1) cooperative      — 합의 가속, 반대 의견 최소화
   2) standard         — 평소 모드, 합리적 의견 제시
   3) critical         — 모든 주장에 근거 요구, 잠재 리스크 적극 발굴
   4) devil's-advocate — 다수 의견에 의도적 반대 제기

   선택?
[사용자] {번호}

▶ {에이전트2} ({팀명} {역할})
... (동일하게 모든 에이전트 순회)
```

> 단축: 사용자가 "전원 비판적" / "전원 표준" / "전원 협력" 등 일괄 지시 시 — 순회 생략하고 일괄 적용.

---

### 통합 결과 출력 (MANDATORY)

4단계 완료 후 최종 구성표 출력. 사용자가 항목별 변경 가능:

```
✅ 최종 토론 구성:

| 팀     | 에이전트   | 역할 | 페르소나               | 비판 모드          |
|--------|-----------|------|----------------------|-------------------|
| {팀1}  | {에이전트1}| 팀장 | {persona_id}         | {critique_mode}   |
| {팀1}  | {에이전트2}| 팀원 | {persona_id}         | {critique_mode}   |
| {팀2}  | {에이전트3}| 팀장 | {persona_id}         | {critique_mode}   |
| ...    | ...        | ...  | ...                  | ...               |

이대로 진행할까요? (Y / 특정 항목 변경)
```

변경 응답 처리:
- "Y" → 토론 시작
- "researcher 페르소나 변경" → [3/4]의 해당 에이전트 단계로 되돌아가 재선택
- "qa 비판 모드 변경" → [4/4]의 해당 에이전트 단계로 되돌아가 재선택

---

## § 에이전트 배정 기준

A~F는 기본값. **필요한 것만 선택, 필요하면 추가**. D는 항상 필수.

| 페르소나 | 실제 에이전트 | 역할 | 포함 조건 |
|----------|--------------|------|---------|
| A | main | 토론 중재, 합의 도출, 데드락 감지 | 항상 |
| B | scout + coder 관점 | 코드베이스 현황, 기술적 실현 가능성 | 코드/구현 논의 시 |
| C | planner | 아키텍처 초안, 전체 설계 방향 | 설계/구조 논의 시 |
| D | researcher / critic(researcher) | 수학적/생물학적 결함 지적 | **항상 필수** |
| E | qa | 구현 오류 탐지, 테스트 가능성 | 코드 변경 포함 시 |
| F | searcher | 최신 논문·사례 수집 | 외부 근거 필요 시 |

**제외 규칙**: 코드 변경 없는 이론 토론 → B, E 제외 / 논문 근거 불필요 → F 제외 (D는 제외 불가)
**모델 배정**: opus(비판적 검토·타당성·수식) / sonnet(설계·탐색·구현) / haiku(빠른 검증·단순 수정)

---

## § 토론 프로세스

**원칙**: 직접 참여 에이전트 전원 동의까지 내부 진행. 데이터 전달 시 § _workspace 규칙 적용.

### [Subagent 모드] Round 실행

```
Round N:
  1. 참여 에이전트를 subagent로 spawn (Agent 도구, subagent_type 지정)
  2. 각 prompt에: 역할·담당 항목·전체 맥락·이전 라운드 요약(discuss-state.md)·"의견 반환" 지시
  3. 반환 즉시 discuss-state.md에 append (발화자 + 의견 요약)
  4. 전 subagent 반환 완료 후: `### Round N 종료` + 합의 여부 추가
  5. 합의 체크
```

### Subagent Spawn Prompt 템플릿 (MANDATORY)

> Step 0.6 결과에 따라 `[TEAM: ...]` `[ROLE: ...]` `[PERSONA: ...]` `[CRITIQUE_MODE: ...]` 헤더 자동 주입.
> 페르소나 본문·비판 모드 강령은 `~/.claude/rules-lazy/agent-personas.md` 참조.

```
[SKILL_DEPTH: 1]
[TEAM: {team_name}]
[ROLE: {팀장|팀원}]
[PERSONA: {persona_id}]
페르소나 강령: {agent-personas.md에서 자동 복사}
우선순위: {agent-personas.md 우선순위 필드}
산출물 스타일: {agent-personas.md 산출물 스타일 필드}

[CRITIQUE_MODE: {cooperative|standard|critical|devil's-advocate}]
{모드별 행동 강령 — agent-personas.md § 비판 모드 표 참조}

너는 {discuss_topic} 토론 {team_name}의 {name} ({팀장|팀원})이다.
팀원: {같은 팀 다른 에이전트 목록과 각자의 페르소나·비판 모드 요약}
토론 주제: {주제}
담당 세분 항목: {항목 목록}

{# 비연구 discuss인 경우에만 #}
researcher는 비판적 연구 검토자이지만, 본 discuss에서는 **비판적 검토자**로 참여합니다.
수학적 결함, 논리적 모순, 실현 불가능한 가정을 집중적으로 지적하십시오.

{# 팀원 ≥ 3명인 경우 — devil's advocate 배정 (MANDATORY) #}
팀원이 3명 이상이므로 반드시 1명을 **비판자(devil's advocate)** 역할로 명시 배정한다.
비판자는 지배적 의견에 의도적으로 반론을 제기하여 조기 수렴·동의 편향을 방지한다.
근거: ACL 2025 "Voting or Consensus: How to Improve LLM's Performance on Factual Questions?" —
역할 다양성 없으면 LLM 멀티에이전트 토론에서 동의 편향(sycophantic convergence) 발생.
비판자 배정 형식: "[비판자: {name}] — 지배적 합의에 의도적 반론 제기, 근거 요구"

=== 이전 라운드 기록 ===
{discuss-state.md 전체 내용}
========================

지시:
- Round {N} 의견 작성. 형식: [Round N — {name}] / 의견: ... / 근거: ... / 합의 여부: 동의 또는 반대(쟁점 명시)
- 코드 수정 금지 — 분석·의견 제시만.
- 200자 초과 데이터는 _workspace/{name}_{주제}.md 저장 후 경로만 반환.
- 결과 반환 후 즉시 종료.
```

**devil's advocate 배정 예시** (팀원 3명 이상):
```
팀 구성:
  planner (teammate)          — 설계 제안
  researcher (teammate)       — 비판적 검토
  [비판자: coder] (subagent)  — devil's advocate, 설계안에 의도적 반론 제기
  scout (subagent)            — 코드베이스 현황 탐색
```

### [Teammate 모드] Round 실행

```
사전: TeamCreate({team_name}) 호출 → 팀 생성 확인

Round N:
  1. Agent(team_name, name, subagent_type)로 spawn. prompt 서두에 [SKILL_DEPTH: 1] 포함
  2. 의견 제시 → SendMessage 상호 교류
     → 200자 이하: SendMessage 직접 / 200자 초과: _workspace 저장 후 경로 전달
     → **SendMessage 1건 발송 직후 discuss-state.md에 즉시 append** (MANDATORY)
  3. Round 완료: `### Round N 종료` + 합의 여부 추가
  4. 합의 체크. 컨텍스트 70%+ → § 런타임 자동 전환 실행
```

**teammate 중복 생성 방지**: agent-routing.md § Teammate 중복 생성 방지 준수.

### 합의 체크 흐름 (방식 무관 공통)

```
Round N 결과
  → 전원 동의 → 합의 → 사용자 보고 → § 종료 순서 실행
  → 불합의 → 불합의 쌍 특정 → Round N+1 (불합의 쌍만 spawn)
    prompt: 각자 Round N 입장 + 상대방 입장 + "합의점 도출" 지시
    → 재합의 체크 → 남은 불합의 쌍 있으면 반복
    → 동일 쌍·동일 쟁점 5회 후에도 불합의 → 에스컬레이션

⚠️ 에스컬레이션 형식:
쟁점: {내용}
{에이전트 A} 입장: ...
{에이전트 B} 입장: ...
최종 결정을 내려주세요.
```

---

## § 설득 공격 방어 (MANDATORY — Scientific Reports 2026)

multi-agent debate에서 에이전트 한 명이 강한 설득 어조를 사용하면 다른 에이전트가 근거 검증 없이 동의하는 현상 실증됨. 합의 오염 방지를 위해:

### 라운드 운영 규칙

> **라운드 상한 계층 (세 숫자는 모순 아님)**: 운영 hard cap **3** → 합의 실패 시 judge 쟁점 재구성으로 **+1 (전체 4)** → **5회 초과**는 시스템 최후 안전장치(강제 에스컬레이션). "동일 쌍·동일 쟁점 5회"는 쌍 단위 별도 카운터.

- **라운드 수 hard cap**: ≤ 3 (현재 운영 동일)
- **이탈 감지**: 한 에이전트가 다음 조건 만족 시 발언권 박탈
  - 동일 라운드 내 발화 길이가 평균의 2배 초과
  - 근거 인용 없이 단정적 결론만 반복
  - 다른 에이전트의 근거를 검토 없이 부정

### 합의 도출 추가 규칙
- **만장일치 ≠ 신뢰**: 만장일치라도 devil's advocate 의견이 1라운드 이상 유지되었는지 확인
- 1라운드 만에 합의 → 조기 수렴 의심 → 강제 1라운드 추가
- 합의 실패 시 → judge(main)가 prompt 재작성 후 Round N+1 (CONSENSAGENT 패턴)

### consensus quality 지표
| 지표 | 기준 | 합의 신뢰도 |
|------|------|------------|
| 라운드 수 | ≥ 2 | 높음 |
| devil's advocate 발언 횟수 | ≥ 1 | 높음 |
| 근거 인용 비율 | ≥ 70% | 높음 |
| 1라운드 만장일치 | — | **낮음 — 추가 검증 필요** |

근거: Scientific Reports 2026 "Persuasion driven adversarial influence in multi-agent LLM debate", ACL 2025 Voting or Consensus.

---

## § 합의 실패 시 prompt 재작성 (CONSENSAGENT 패턴)

라운드 ≤ 3 모두 합의 실패 시:
1. judge(main)가 불합의 핵심 쟁점 추출 (가장 빈번한 disagreement)
2. 쟁점을 명시적 질문으로 변환 → spawn prompt 재작성
3. Round N+1 실행 — 단, 라운드 수는 전체 4 이내
4. 4라운드까지도 실패 시 → main이 직접 결정 (사용자 합의 요청)

근거: CONSENSAGENT (2025) — disagreement는 prompt 결함의 신호. 단순 라운드 추가보다 prompt 재작성이 효과적.

---

## § 상태 파일 형식

`~/.claude/teams/{team_name}/discuss-state.md`:

```markdown
# {team_name} 토론 상태

## 주제
{주제}

## 세분 항목
1. {항목} — 담당: {에이전트}

## 참여 에이전트
- {페르소나}: {역할} ({모델}) [teammate/subagent]

## 실행 방식
{teammate / subagent / 전환 이력}

## 라운드 기록

### Round 1
{에이전트명}: {의견 요약} / 합의 여부: {동의/반대}
불합의 쌍: {A} ↔ {B} — 쟁점: {내용}

### Round 1 종료
합의: {여부}

## 최종 합의
{합의 내용 또는 에스컬레이션 사유}

## _workspace 파일 목록
- _workspace/{팀원명}_{주제}.md — {내용 요약}
```

---

## § 세션 재개 시 복원 프로토콜

```
1. ~/.claude/teams/ 하위 discuss-state.md 존재 확인
2. 존재 시 사용자 알림:
   "이전 토론 중단: {team_name}, 마지막 진행: Round {N}, 불합의 쌍: {A} ↔ {B}. 이어서 진행할까요? (y/n)"
3. y → 상태 파일 로드 → 사전 조건 체크 → teammate/subagent 재개
4. n → 상태 파일 삭제 → 새 토론
```

---

## § 팀 구성 보고 형식

```
📋 팀 구성 보고:
┌──────────────────────────────────────────────────────────────┐
│ 토론 주제: {주제}                                              │
│ 세분 항목: N개                                                 │
│ 현재 컨텍스트: N% → 실행 방식: {teammate / subagent 전용}      │
│ discuss 유형: {연구 / 비연구} → D역할: {researcher / critic}   │
├──────────────────────────────────────────────────────────────┤
│ 멤버 구성:                                                      │
│  ✅ A (중재자): main                                            │
│  ✅ {페르소나}: {에이전트} ({모델}) [teammate] — 포함 이유      │
│  ✅ D (비판적검토): researcher ({모델}) [teammate]              │
│  ❌ {페르소나}: 제외 — 이유                                     │
├──────────────────────────────────────────────────────────────┤
│ 회의록 경로: ${LONG_TERM_ROOT:-~/workspace/_data/workspaces/user/.claude/long-term}/          │
│   {project}/meetings/{year}/{month}/{date}/{회의_제목}/회의록.md │
│ 상태 파일: ~/.claude/teams/{name}/discuss-state.md           │
└──────────────────────────────────────────────────────────────┘
이 구성으로 진행할까요?
```

---

## § 재귀 호출 (SKILL_DEPTH=1 강제)

/discuss 내에서 다시 /discuss 호출 가능 — 단, TeamCreate 금지(전원 subagent), ≤3명, 라운드 ≤1, prompt ≤200자.
상세: `rules-lazy/skill-autonomy.md` § 깊이 제한·/discuss 재귀 특례 (agent-routing.md § 스킬 자율 호출 공통 규칙이 이 파일로 위임)

---

## § teammate 실행 환경 선택 가이드

| 모드 | 동작 | 권장 상황 |
|------|------|---------|
| in-process (auto) | 단일 Claude 세션이 모든 agent를 turn 단위로 호출 — 동기적 | 일반 토론·합의 (현재 기본값) |
| tmux | 패널별 독립 Claude 세션, SendMessage 비동기 | 5명+ 대규모 토론, 장시간 독립 작업 |
| bg(데몬) | 백그라운드 데몬 — agents view에서 관리 | 학습 모니터링, 비대화형 자동화 |

`settings.json` `teammateMode: "auto"` — 현재 in-process 기본.

---

## § Cross-Watch 프로토콜

상세: `~/.claude/skills/paper/SKILL.md` § Cross-Watch 프로토콜 (실 정의 위치 — 구 cross-watch.md는 paper 스킬로 통합됨)
분석팀 + 논문팀 동시 활성 시 자동 적용.

---

## 생략 조건

- 단순 버그/syntax 오류 수정
- 명확한 정답이 있는 경우
- 사용자가 "즉시 진행" 명시 시

---

## 사용 예시

```
/discuss HC 파라미터 10개의 생물학적 타당성
/discuss LoRA vs Adapter 성능 비교
/discuss                    ← 현재 맥락 기반 자동 주제 감지
```
