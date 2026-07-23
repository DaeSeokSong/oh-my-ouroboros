# 모델 배정 — 위임 규칙 + 분리 원칙 (lazy)

> **로드 시점**: 위임 판단 후 상세 룰 참조 시 (Step 1.5 모델 결정 후)
> **상위 파일**: `~/.claude/rules/model-assignment.md`

## §4 subagent 모델 배정 요약

> 모델별 역할 정의(Opus 직접 처리 / Sonnet / Haiku 조건)는 상위 파일 `rules/model-assignment.md` §1~§3 단일 출처. 여기서 중복 정의하지 않는다.
> 운영 원칙: 불확실 시 **Sonnet 기본값**, 작업 중 부적합 판단 시 즉시 상위 모델로 재배정.

> **역할 경계**: `rules/model-assignment.md`(always-on) = "어떤 모델을 쓸지" 판단 기준 / 이 파일(lazy) = "어떻게 위임·분리할지" 집행 상세. 상보 관계 — 병합하지 않는다.

---

## §5 위임 규칙 (MANDATORY)

### Opus가 직접 처리하면 안 되는 작업 (아래는 반드시 위임)

| 작업 유형 | 위임 대상 | 이유 |
|----------|----------|------|
| 단일 파일 코드 수정 (수식 무관) | Sonnet | 로직 판단 불필요 |
| 파일 탐색·Grep·Glob 작업 | Haiku | 순수 탐색 |
| 반복 패턴 일괄 적용 (3개+) | Haiku | 동일 작업 반복 |
| 규칙/스킬/에이전트 .md 파일 수정 | Sonnet | 텍스트 편집 |
| Git 커밋·diff·log | Sonnet (gitops) | 정형 작업 |
| Confluence 페이지 생성·수정 | Sonnet (docs) | MCP 호출 |
| QA 검증 (호출부·import 체크) | Sonnet (qa) | 검증 작업 |
| 테스트 실행·결과 요약 | Haiku | 실행+보고 |
| 메모리 파일 업데이트 (decisions.md, MEMORY.md, handover.md) | Haiku | 단순 텍스트 추가 |
| 인터넷 검색 (WebSearch/WebFetch) | Sonnet (searcher) | 검색+종합 — **단 단발(1~2회) 근거·사실확인은 main 직접 허용**(§5 도구 호출 제한 표 line 61·`tavily-auto.md` 호출 주체 규약). 광범위·반복·대용량만 searcher 위임 |
| 에러 분석 후 코드 수정 | Sonnet (coder) | 분석은 Opus, 수정은 분리 |
| 연속 Glob/Grep 3회+ | Haiku (scout) | 탐색 묶음 위임 |
| 다중 파일 Read 3개+ | Haiku (scout) | 읽기+요약 위임 |
| git diff/log 결과 분석 | Sonnet (gitops) | 긴 출력 Opus 컨텍스트 방지 |

### Opus가 직접 처리해야 하는 작업 (위임 금지 — §1 재확인)

- 사용자와 합의가 필요한 설계 판단
- 수식·생물학적 타당성 포함 분석
- 아키텍처 변경 결정
- 복합 디버깅 (인과관계 + 수정이 묶인 경우)
- /discuss 토론 중재

### 위임 미실행 시 자가 진단

Opus가 직접 작업을 시작하기 전 자가 질문:
```
"이 작업에 수식·생물학·아키텍처·합의 판단이 포함되어 있는가?"
  YES → Opus 직접 처리
  NO  → "왜 subagent에 위임하지 않는가?"
        → 정당한 사유 없음 → 즉시 위임
```

### Opus 직접 도구 호출 제한 (MANDATORY)

Opus 메인 세션이 직접 호출할 수 있는 도구를 제한한다. 아래 도구는 subagent를 통해서만 사용한다:

| 도구 | Opus 직접 사용 조건 | 위반 시 위임 대상 |
|------|-------------------|----------------|
| **Edit/Write** | 위임 생략 조건 해당 시만 (단일 Edit 1회 + 단일 파일) | Sonnet coder |
| **WebSearch/WebFetch/Tavily MCP** | 단발(1~2회) 근거·사실확인은 main 직접 허용 (적극 모드 — 단일 출처: `tavily-auto.md` § 호출 주체 규약). 광범위·반복·대용량은 searcher 경유 | Sonnet searcher |
| **Bash (git 명령)** | 금지 — `git status` 확인용 제외 | Sonnet gitops |
| **MCP (Confluence/Jira)** | 금지 — 예외 없음 | Sonnet docs |

### Opus→Sonnet 실행 분리 원칙 (MANDATORY)

Opus는 **판단·계획·보고**만 담당하고, **실행**은 subagent에 위임한다:

```
Opus 역할: 사용자 대화 → 요구 분석 → 계획 수립 → 위임 → 결과 수신 → 사용자 보고
Sonnet 역할: 코드 수정 → 파일 작성 → Git 작업 → QA 검증 → 문서 작성
Haiku 역할: 파일 탐색 → 메모리 업데이트 → 단순 수정 → 로그 분석
```

| 상황 | Opus | Sonnet/Haiku |
|------|------|-------------|
| 사용자가 "수정해" | 계획 수립 + 보고 | 실제 Edit/Write 실행 |
| 사용자가 "커밋해" | — | gitops가 전체 처리 |
| 사용자가 "검색해" | — | searcher가 검색 + 요약 |
| 에러 발생 | 원인 분석 | coder가 수정 실행 |
| QA 필요 | — | qa가 검증 실행 |
| 메모리 기록 | 기록 내용 결정 | Haiku가 파일 Write |

---

## §6 second-opinion 교차검증 (opt-in — 메인 모델 판단 보상)

> **목적**: 메인 세션 모델이 최상위 티어가 아닐 때(예: Opus 운영기), §1 고위험 직접 처리 결정의 판단 품질을 독립 검토로 보상한다.

- **트리거**: 사용자가 "second-opinion"/"교차검증"/"정밀 검토" 명시 요청 시에만 (기본 off — 토큰 절약)
- **대상**: §1 결정 중 아키텍처 변경·수식 구현·크로스 모듈 영향 (되돌리기 비싼 결정)
- **방법**: main이 결정 초안+근거를 정리 → Sonnet subagent(planner 또는 researcher 페르소나)에 **세션 히스토리 없이 결정문만** 전달 → 독립 검토(결함·대안·리스크) 1회 → main이 차이점 비교 후 사용자 보고
- **제한**: 1결정 1회, 추가 라운드 금지 (라운드 필요 시 /discuss로 승격)

## §7 Whole-Job 예외 상세 (2026-07-21 harness-engineering 이식 — 2026-07-23 토큰 점검으로 always-on에서 이관)

- **판단 신호**: 원인 분석↔수정↔검증이 같은 맥락을 반복 참조하고 중간 산출물 전달이 장문이면 결합도 높음 — §2·§3 기준으로 단계별 쪼개지 말 것.
- **근거**: 잘못된 분해→subagent 재작업 비용은 2-렌즈 점검(`agent-routing.md`)이 이미 인정하는 손실. 분업 오케스트레이션의 반대축 관점("Give one agent the whole job" — lopopolo/harness-engineering `docs/whole-job/`)을 예외 조항으로 흡수.
- **남용 가드**: 독립 병렬 가능한 작업(라우팅 0.5 parallel-dispatch)엔 적용 금지 — 판단 기준은 작업 수가 아니라 **단계 간 결합도**. 위임 사전 보고의 "whole-job: {결합 근거 1줄}"이 남용 감사 추적점.
