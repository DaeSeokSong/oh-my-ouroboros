# Parallel Dispatch — 병렬 Agent 분산

> **로드 시점**: 독립적인 복수 작업을 동시에 실행해야 할 때 (한 응답에 Agent 도구 N개 동시 호출)
> **비용 모델**: Pro/Max 구독 토큰만 (추가 비용 없음)
> **참조 스킬**: `superpowers:dispatching-parallel-agents`

---

## subagent vs teammate 비교표

| 항목 | parallel-dispatch (subagent × N) | teammate (TeamCreate) |
|------|----------------------------------|----------------------|
| 호출 방식 | 한 응답에 `Agent(subagent_type=...)` N개 동시 호출 | `TeamCreate` → `Agent(team_name=..., name=...)` |
| 통신 | 없음 (단방향, 결과만 반환) | `SendMessage` 양방향 교환 가능 |
| broadcast | 불가 | 가능 (daemon 자동 처리) |
| 토론·합의 | 불가 | 가능 (multi-round) |
| 결과 통합 | main이 N개 결과 수신 후 통합 | 팀 내 자율 합의 후 리드가 보고 |
| 적합 작업 | 독립 도메인 · 병렬 실행 · 1회성 | 반복 교환 · 합의 · 상호 검수 필요 |
| 비용 | 낮음 (TeamCreate 오버헤드 없음) | 높음 (daemon worker 토큰 + 라운드) |
| 명령서 형식 | 자체완결(self-contained) prompt | Spawn Prompt 템플릿 + SKILL_DEPTH 포함 |

---

## 이해를 돕는 비유

**parallel-dispatch** = 레스토랑에서 4명의 손님이 각자 다른 메뉴를 주문. 주방의 4명 셰프가 동시에 각자의 요리를 만든다. 서로 소통 없이 자기 요리에만 집중. 웨이터(main)가 4개 접시를 받아 테이블에 올린다.

**teammate** = 셰프 한 명과 보조 한 명이 하나의 코스 요리를 협력해 만든다. 셰프가 "소스 더 넣어" 하면 보조가 반응. 여러 라운드를 거쳐 완성된 하나의 코스가 나온다.

> 같은 테이블에 4가지 독립 요리가 필요하면 parallel-dispatch. 하나의 완성도 높은 코스가 필요하면 teammate.

---

## 용도 결정 트리

```
Q1. 각 작업이 서로 독립적인가? (다른 작업의 결과 없이 실행 가능)
  ├─ YES → Q2로
  └─ NO  → teammate (순차 의존성 → SendMessage 필요)

Q2. 작업 간 의견 교환·합의가 필요한가?
  ├─ YES → teammate (브로드캐스트·토론 필요)
  └─ NO  → Q3로

Q3. 동일 에이전트가 반복(≥3회) 교환할 가능성이 있는가?
  ├─ YES → teammate (G-E Loop / Ralph 루프 포함)
  └─ NO  → Q4로

Q4. 작업이 단일인가 복수인가?
  ├─ 단일 → 단일 subagent (parallel-dispatch 불필요)
  └─ 복수 (2개+) → parallel-dispatch (동시 Agent 호출)
```

---

## 결정 트리 적용 예시

| 시나리오 | 선택 | 이유 |
|---------|------|------|
| foo.py, bar.py, baz.py 각자 독립 수정 | parallel-dispatch | 파일 간 의존성 없음, 동시 가능 |
| 아키텍처 토론 (planner ↔ researcher) | teammate | 상호 의견 교환 필수 |
| coder 수정 → qa 재검증 → coder 재수정 가능성 | teammate (G-E Loop) | 반복 교환 ≥3회 가능 |
| scout 1회 파일 탐색 | 단일 subagent | 복수 작업 아님 |
| foo.py, bar.py 독립 수정 + qa 1회 검증 | parallel-dispatch(coder×2) → qa | 수정은 독립, qa는 이후 단계 |
| 검색 1회 (searcher) | 단일 subagent | 1회성, 합의 불필요 |

---

## § Tournament 패턴 (N-후보 경쟁 → rubric 채점 채택)

> 공식 Dynamic Workflow 6패턴 중 하나의 경량(opt-in 불요) 버전. 해(解) 공간이 넓어 단일 시도로는 품질이 불확실할 때 사용 — 설계 선택, 네이밍, 접근법 비교, 알고리즘 전략 등.

### 일반 parallel-dispatch와의 차이

| | 일반 parallel-dispatch | Tournament |
|---|---|---|
| 각 Agent | **서로 다른** 독립 작업 | **동일 작업, 다른 전략** N개 |
| 통합 | N개 결과 병합 | **judge가 채점 → 승자 채택** (+ 차순위 강점 graft) |
| 추가 단계 | 없음 | 채점 단계 1회 (별도 judge) |

### 실행 흐름

```
1. main이 동일 작업을 서로 다른 N개 전략으로 분해 (예: MVP-우선 / 리스크-우선 / 사용자-우선)
2. parallel-dispatch로 N개 후보 동시 생성 (각 self-contained, 전략만 상이)
3. judge subagent(또는 main)가 사전 rubric으로 채점 → 승자 1개 채택
   - 자기편향 방어: 생성자와 다른 주체가 채점 (가능하면 별도 judge agent)
   - 동률/모호 → 차순위 후보의 강점을 승자에 graft
4. main이 채택 결과 + 채점 근거 보고
```

### 사용 판단

| 쓴다 | 안 쓴다 |
|------|--------|
| 해 공간 넓음 + 단일 시도 품질 불확실 | 정답이 하나로 명확한 작업 |
| 설계/네이밍/접근법 선택 | 단순 수정·탐색 |
| 1000+ 행 정렬 등 단일 prompt 품질 저하 작업 | — |

> 대규모·반복 토너먼트(후보 多·라운드 多)는 모드 B(`Workflow` 도구 — `rules-lazy/dynamic-workflow.md`) 권장. 소규모 1회 토너먼트는 본 parallel-dispatch로 충분.

---

## § 동시 Agent 상한선 (MANDATORY)

| 항목 | 상한 | 근거 |
|------|------|------|
| 한 turn 최대 Agent 수 | ≤ 8 | Anthropic 내부 사례의 16 병렬 보고는 fork mode 전제. 일반 spawn은 8 이내 권장 |
| 작업 예상 시간 | ≥ 2분/작업 | overhead 손익 분기 — 30초 이하 작업은 직렬이 빠름 |
| subagent 합산 컨텍스트 | ≤ 메인의 30% | 결과 통합 단계에서 메인 컨텍스트 폭증 방지 |

상한 초과 시: 순차 배치 또는 ralph-loop으로 분할.
근거: Anthropic "Building Effective Agents" — Parallelization 패턴.

> ⚠ LLM 제어 retry 금지 — 코드 제어 exponential backoff + cap (`error-handling.md` § Retry 정책 참조)

⚠ Augment Code 2026 실측: 3 에이전트 구성이 실제 5~15x 청구되는 사례 — 컨텍스트 재전달 중복 과금, 역할 정의 매 호출 과금, 검증 계층 중첩이 주요 원인. § 비용 폭증 방지 참조.

---

## § 결과 통합 책임자 (MANDATORY)

호출 주체(spawn한 에이전트)가 통합 책임을 진다:
- main이 dispatch → main이 통합
- coder가 dispatch → coder가 통합 후 main 보고
- qa가 dispatch (ralph) → qa(팀장)가 통합 후 main 보고

> **전제 (소집 실행 주체)**: coder·qa가 "dispatch"하려면 Agent 도구가 있어야 한다 — 이는 **teammate·main 컨텍스트일 때만** 성립한다. 일반 subagent 컨텍스트(Agent 도구 없음)에선 coder·qa가 직접 dispatch 불가 → main에 "parallel-dispatch 적합" 신호로 반환하고 **main이 dispatch + 통합**한다(`rules/agent-routing.md` § "소집"의 실행 주체).

통합 후 보고 형식: "subagent N개 결과: {요약 3줄}, 충돌: {있음/없음}, 통합 결론: {1줄}"

---

## 자동 트리거 조건

아래 **모두** 충족 시 parallel-dispatch 사용:

| 조건 | 기준 |
|------|------|
| 독립 도메인 2개+ | 각 Agent가 다른 작업의 출력 없이 실행 가능 |
| 순차 의존성 없음 | Agent A가 완료돼야 Agent B가 시작되는 관계 ❌ |
| 컨텍스트 < 60% | 60% 이상이면 순차 실행 권장 |
| 결과 통합 가능 | main이 N개 결과를 수신 후 통합할 수 있는 구조 |

---

## 금지 케이스

| 케이스 | 이유 |
|--------|------|
| 공유 state 수정 | 동시 수정 시 충돌 — 예: 동일 파일에 두 coder가 동시 Edit |
| 순차 의존성 있음 | Agent B가 Agent A의 결과를 입력으로 필요 |
| 디버깅 인과 추적 | 인과 체인을 따라가는 tracer mode는 순차 단계 필요 |
| 합의·설계 결정 | 에이전트 간 의견 조율 필요 → teammate 사용 |

---

## 호출 형식

한 응답에 `Agent` 도구를 N개 **동시** 호출한다. 각 prompt는 **self-contained** (앞 작업 결과 참조 없음):

```
# 예시: coder 2개 동시 dispatch
Agent(
  subagent_type="coder",   # 에이전트명 — 모델은 별도 model 파라미터 (예: model="sonnet")
  description="sonnet: Modify foo.py independently",
  prompt="[SKILL_DEPTH: 0]\n\nfoo.py의 {함수명}에서 {수정 내용}을 적용하라. ...(self-contained 지시)"
)

Agent(
  subagent_type="coder",   # 에이전트명 — 모델은 별도 model 파라미터 (예: model="sonnet")
  description="sonnet: Modify bar.py independently",
  prompt="[SKILL_DEPTH: 0]\n\nbar.py의 {함수명}에서 {수정 내용}을 적용하라. ...(self-contained 지시)"
)
```

> ⚠️ 각 prompt는 이전 Agent 결과를 참조하지 않는다. 공유 state 없음.

---

## main 통합 패턴

N개 Agent 결과 수신 후 main이 통합하여 사용자에게 보고:

```
[parallel-dispatch 결과 통합]
- Agent 1 (foo.py): DONE — {요약 1줄}
- Agent 2 (bar.py): DONE — {요약 1줄}
- Agent 3 (baz.py): DONE — {요약 1줄}

통합 완료. QA 검증으로 진행합니다.
```

실패 Agent가 있으면 해당 Agent만 재시도하거나 main 에스컬레이션.

---

## § Fork mode (Claude Code v2.1.117+, SDK v2.1.121+, 확인일 2026-10-17, 기준 Claude Code 2.1.301)

부모 context 상속 + prompt cache 재사용으로 비용 절감.
활성화: `CLAUDE_CODE_FORK_SUBAGENT=1` env-var.

**v2.1.121부터(확인일 2026-10-17) 비대화형 세션(`claude -p`, SDK) 지원** — 이전 대화형 전용 제한 해제.

| 조건 | 권장 |
|------|------|
| 부모 context > 50K tokens + 동일 base로 다수 subagent | ✓ fork 권장 |
| subagent가 추가 subagent 생성 필요 | ✗ fork 금지 (깊이 1 제한) |
| 작업 간 context 독립성 필요 | ✗ 일반 subagent 권장 |
| skills의 allowed_tools 사전 선언 가능 | ✓ fork + permission 격리 → 승인 루프 제거 |

근거: GitHub Issue #54163, Anthropic v2.1.121 changelog (2026, 확인일 2026-10-17)

---

## 노트

- teammate 간 SendMessage, broadcast, mailbox는 **daemon이 자동 처리** — 사용자 개입 불필요.
- 사용자 개입이 필요할 때만 `inputNeededNotifEnabled=true` 알림 자동 발송.
- Shift+Down은 선택적 확인용 — 필수 조작 아님.
- parallel-dispatch는 TeamCreate 없이 즉시 실행 → teammate 오버헤드 없음.

## main 추천 패턴 (자율 dispatch 권한 없는 에이전트용)

자율 호출 권한이 없는 에이전트(docs/researcher/planner)가 parallel-dispatch 적합한 작업을 받았을 때, **main이 사용자에게 추천**한다.

### Case B — main 자동 감지 + 추천

main이 작업 분석 중 아래 패턴 감지 시 사용자에게 추천:

| 에이전트 | 추천 트리거 |
|---------|-----------|
| docs | "페이지 N개 업데이트" — cross-link 없는 페이지 |
| researcher | "논문 N편 동시 평가", "여러 실험 비교" |
| planner | (보수적) 다중 설계 옵션 평가 — 사용자 명시 시만 |

추천 형식:
```
💡 이 작업은 parallel-dispatch (병렬 Agent)로 가능합니다:
   - {Agent} × N개 동시 dispatch
   - 예상 시간 단축: 약 N배
   - 비용: 토큰 N배 (동시 진행이므로 누적 시간 절감)
   진행할까요? (Y/N)
```

→ 사용자 Y → main이 직접 Agent N개 dispatch
→ 사용자 N → 순차 실행

### Case C — 사용자 명시 동일 에이전트 N개 요청

사용자가 **명시 요청** 시 추천 단계 생략 — 즉시 N개 dispatch.

판단 패턴:
- 숫자 명시: "researcher 3명", "coder 5개"
- 복수형: "여러 researcher", "coder들"
- 사용자가 "parallel-dispatch" / "병렬로" / "동시에" 직접 명시

### 다수 호출 기능 통합 매핑

parallel-dispatch는 단독 스킬이지만, 아래 다수 호출 기능과 결합 가능:

| 기능 | parallel-dispatch 결합 방식 |
|------|----------------------------|
| `/discuss` | TeamCreate로 teammate 다수 소집 시, 동일 역할 N명이 독립 의견 작성 필요 → 라운드 시작 단계만 parallel (이후 SendMessage 라운드는 순차) |
| `TeamCreate` | teammate 자체가 다수 소집 — 독립 작업 phase에서 parallel-dispatch 결합 가능 |
| `workflow` | 워크플로우의 phase가 서로 독립이면 parallel-dispatch로 phase 동시 실행 |
| `/paper-read` | 사용자가 N편 동시 요청 시 paper-read 본문이 N개 searcher Agent 동시 발사 |

→ 이런 다수 호출 기능을 main이 호출할 때, **독립 phase 또는 독립 의견 단계**에서는 parallel-dispatch 활용 권장.

### 추천 안내 (Case B) 후 사용자 거부 시
- 순차 처리 진행
- Mem0에 거부 패턴 저장 (선택) → 동일 상황 재발 시 재질문 안 함 (사용자 선호 학습)

---

## § Prompt cache 경계 설계 (MANDATORY — 비용 최적화)

LMCache 2025 실측: 정적/동적 컨텍스트 분리로 prefix cache 재사용율 92% 달성 → 2M 토큰 기준 비용 81% 절감 ($6.00 → $1.152), TTFT 5~10x 단축.

### 정적 / 동적 분리 원칙

| 분류 | 예시 | 위치 |
|------|------|------|
| 정적 (캐시 가능) | system prompt, 규칙·스킬 본문, 프로젝트 메타 | spawn prompt 서두 (캐시 경계 안쪽) |
| 동적 (매 턴 갱신) | working memory, runtime context, 최근 tool 결과 | spawn prompt 말미 (캐시 경계 밖) |

### subagent 간 컨텍스트 재사용

- 같은 정적 컨텍스트로 N개 subagent 발사 시 → fork mode 사용 → prefix cache 공유
- 다른 정적 컨텍스트 필요 시 → 별도 subagent (prefix 다름)
- 동적 부분은 매번 전달 — 캐시 미스 정상

근거: LMCache 2025 (Claude Code context engineering 분석), ProjectDiscovery prompt caching 사례.

---

## § 비용 폭증 방지 — Multi-agent Cost Compounding

근거: Augment Code 2026, Deloitte Q4 2025 — 멀티에이전트 배포에서 실제 청구가 예산 대비 5~15x인 사례 다수.

| anti-pattern | 발생 원인 | 대응 |
|------|----------|------|
| 컨텍스트 재전달 중복 과금 | 매 subagent마다 동일 context 재전송 | fork mode 또는 prefix cache 공유 |
| 역할 정의 매 호출 과금 | spawn prompt에 긴 role 정의 반복 | 정적 부분 캐시 경계 안쪽 배치 |
| LLM 제어 retry 무한 중첩 | 에이전트가 실패 시 스스로 재호출 결정 | **금지 — 코드 제어 retry + exponential backoff + cap 명시** |
| 검증 계층 중첩 | qa가 또 qa 부르기 | 깊이 1 제한 (`SKILL_DEPTH`로 차단) |
| 컨텍스트 rot | 오래된 정보 누적 → 토큰 증가 | 매 cycle 시작 시 핵심 결정만 유지, 나머지 압축 |

근거: Augment Code "Multi-Agent Cost Compounding", techaheadcorp Inference Cost Explosion 2025.
