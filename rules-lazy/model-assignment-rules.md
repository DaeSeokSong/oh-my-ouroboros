# 모델 배정 — 위임 규칙 + 분리 원칙 (lazy)

> **로드 시점**: 위임 판단 후 상세 룰 참조 시 (Step 1.5 모델 결정 후)
> **상위 파일**: `~/.claude/rules/model-assignment.md`
> **머신별 모델 핀**: README.md 에 둔다(2026-07-15 결정, 2026-11-10 상시 머리에서 날짜 이관).
> **능력 불변식**: 메인 세션은 subagent 별칭 opus 이상이어야 §1 표가 성립한다. 그보다 낮은 핀이면 §1 은 opus subagent 위임으로 읽는다.

## 손과 결정의 분리 — 상세 (2026-09-02 Grok 검수 A8, model-assignment.md 이관)

수식·알고리즘 코드의 **타이핑 자체**는 main 이 설계 명세(수식·불변식·인터페이스·테스트 조건)를 쓴 뒤 coder 에게 맡길 수 있고, 채택·검증(수식 대조·실행 증거)은 main 이 한다. planner·researcher 자문 위임 각주와 같은 원리다.

## §4 subagent 모델 배정 요약

> 모델별 역할 정의(메인 세션 직접 처리 / Sonnet / Haiku 조건)는 상위 파일 `rules/model-assignment.md` §1~§3 단일 출처. 여기서 중복 정의하지 않는다.
> 운영 원칙: 불확실 시 **opus subagent 위임**(분리 컨텍스트, 2026-09-08 사용자 결정), 작업 중 부적합 판단 시 즉시 재배정. 회색 지대는 판단이 걸린 일이라 값싼 모델의 기본값 자리가 아니다.
> planner·researcher는 opus 동급 subagent라서 "하위 모델" 위임이 아니라 **분리 컨텍스트 위임**이 목적이다(`rules/model-assignment.md` 머리의 핵심 원칙에서 이관).
> 실측 근거: 14일 482건 중 sonnet 66%·opus 14% — 판단이 걸린 회색지대까지 값싼 모델의 기본값으로 흘렀다.

> **역할 경계**: `rules/model-assignment.md`(always-on) = "어떤 모델을 쓸지" 판단 기준 / 이 파일(lazy) = "어떻게 위임·분리할지" 집행 상세. 상보 관계 — 병합하지 않는다.

---

## §5 위임 규칙 (MANDATORY)

### 메인 세션이 직접 처리하면 안 되는 작업 (아래는 반드시 위임)

| 작업 유형 | 위임 대상 | 이유 |
|----------|----------|------|
| 단일 파일 코드 수정 (수식 무관. **단일 Edit 1회·세션 내 비연속**은 예외로 main 직접, `rules/model-assignment.md` §1 「단일 Edit 예외」) | Sonnet | 로직 판단 불필요 |
| 파일 탐색·Grep·Glob 작업 | Haiku | 순수 탐색 |
| 반복 패턴 일괄 적용 (3개+) | Haiku | 동일 작업 반복 |
| 규칙/스킬/에이전트 .md 파일 수정 | Sonnet | 텍스트 편집 |
| Git 커밋·diff·log | Sonnet (gitops) | 정형 작업 |
| Confluence 페이지 초안 작성 | Sonnet (docs) | 글쓰기 전용 — 조회·게시는 main (`skills/confluence/SKILL.md` §3-1) |
| QA 검증 (호출부·import 체크) | Sonnet (qa) | 검증 작업 |
| 테스트 실행·결과 요약 | Haiku | 실행+보고 ※ 판정 로직(6-Gate·원인 분석)이 걸리면 qa(sonnet), 모파일 §3 단서 |
| 메모리 파일 업데이트 (decisions.md, MEMORY.md, handover.md) | main 직접 | haiku(scout)는 Write 가 없고 기록은 «다음 응답 전 즉시» (`memory-write.md`) |
| 인터넷 검색 (WebSearch/WebFetch) | Sonnet (searcher) | 검색+종합 — **단 단발(1~2회) 근거·사실확인은 main 직접 허용**(§5 도구 호출 제한 표 line 61·`tavily-auto.md` 호출 주체 규약). 광범위·반복·대용량만 searcher 위임 |
| 에러 분석 후 코드 수정 | Sonnet (coder) | 분석은 메인 세션, 수정은 분리 |
| 연속 Glob/Grep 3회+ | Haiku (scout) | 탐색 묶음 위임 |
| 다중 파일 Read 3개+ | Haiku (scout) | 읽기+요약 위임 |
| git diff/log 결과 분석 | Sonnet (gitops) | 긴 출력 메인 컨텍스트 방지 |

### 메인 세션이 직접 처리해야 하는 작업 (위임 금지 — §1 재확인)

- 사용자와 합의가 필요한 설계 판단
- 수식·생물학적 타당성 포함 분석
- 아키텍처 변경 결정
- 복합 디버깅 (인과관계 + 수정이 묶인 경우)
- /discuss 토론 중재

### 위임 미실행 시 자가 진단

메인 세션이 직접 작업을 시작하기 전 자가 질문:
```
"이 작업에 수식·생물학·아키텍처·합의 판단이 포함되어 있는가?"
  YES → 메인 세션 직접 처리
  NO  → "왜 subagent에 위임하지 않는가?"
        → 정당한 사유 없음 → 즉시 위임
```

### 메인 세션 직접 도구 호출 제한 (MANDATORY)

메인 세션이 직접 호출할 수 있는 도구를 제한한다. 아래 도구는 subagent를 통해서만 사용한다:

| 도구 | 메인 세션 직접 사용 조건 | 위반 시 위임 대상 |
|------|-------------------|----------------|
| **Edit/Write** | 위임 생략 조건 해당 시만 (단일 Edit 1회 + 단일 파일) | Sonnet coder |
| **WebSearch/WebFetch/Tavily MCP** | 단발(1~2회) 근거·사실확인은 main 직접 허용 (적극 모드 — 단일 출처: `tavily-auto.md` § 호출 주체 규약). 광범위·반복·대용량은 searcher 경유 | Sonnet searcher |
| **Bash (git 명령)** | 금지 — `git status` 확인용 제외 | Sonnet gitops |
| **MCP (Confluence/Jira)** | 조회·게시는 main 이 직접(`skills/confluence/SKILL.md` §3-1 검토 관문 뒤). docs 는 MCP 가 없고 초안 파일만 쓴다 | Sonnet docs (초안 작성) |

### 메인 세션→Sonnet 실행 분리 원칙 (MANDATORY)

메인 세션은 **판단·계획·보고**만 담당하고, **실행**은 subagent에 위임한다:

```
메인 세션 역할: 사용자 대화 → 요구 분석 → 계획 수립 → 위임 → 결과 수신 → 사용자 보고
Sonnet 역할: 코드 수정 → 파일 작성 → Git 작업 → QA 검증 → 문서 작성
Haiku 역할: 파일 탐색 → 단순 수정 → 로그 분석
```

| 상황 | 메인 세션 | Sonnet/Haiku |
|------|------|-------------|
| 사용자가 "수정해" | 계획 수립 + 보고 | 실제 Edit/Write 실행 |
| 사용자가 "커밋해" | — | gitops가 전체 처리 |
| 사용자가 "검색해" | — | searcher가 검색 + 요약 |
| 에러 발생 | 원인 분석 | coder가 수정 실행 |
| QA 필요 | — | qa가 검증 실행 |
| 메모리 기록 | 기록 내용 결정 | main 이 파일 Write (메모리 파일 갱신은 main 직접) |

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

## §7.1 구현 갈래의 실측 근거 (2026-11-10, 에이전트 정리 10단계 · 사용자 결정 S10L · S10E)

같은 과제(수수료 함수의 시그니처를 바꾸면 호출 모듈 2개와 시험 3개가 함께 바뀜, 채점은 구현자에게 보이지 않는 시험 12개)를 조건마다 5회 쟀다.

| 조건 | 토큰(평균) | 금액(USD, API 단가 환산) | 숨긴 시험 | 재작업 |
|---|---|---|---|---|
| planner(opus) 명세 → coder(sonnet) | 157,752 | 0.9091 | 12/12 × 5 | 0 |
| opus subagent 통째(coder 타입, 명세 없음), effort medium | 88,142 | 0.6027 | 12/12 × 5 | 0 |
| 같은 조건, effort high | 91,351 | 0.6535 | 12/12 × 5 | 0 |
| 새 main 세션(Fable 5.2)이 직접, 1회 | 127,005 | 2.42 | 12/12 | 미측정 |

표의 effort medium · high 는 당시 측정 조건이다. 현행 effort 는 2026-11-12 §9 로 대체돼 `agents/*.md` 머리가 정한다.

- 통째 조건은 토큰이 44% 줄었고 opus 단가로 계산해도 금액이 34% 낮았다. 명세를 넘기면 설계자와 구현자가 저장소를 각각 읽는데 통째 조건은 한 번만 읽는다는 점이 원인으로 보인다(과제 하나의 결과라 단정하지 않는다).
- main 이 직접 하는 쪽은 subagent 대리로 잴 수 없어 새 세션 1회만 봤다. 그 값에는 세션을 시작하며 규칙을 싣는 비용이 들어 있고, 이미 맥락을 가진 main 이 이어서 하는 경우는 재지 못했다. main 모델의 목록 단가(입력 100만 토큰당 Fable 8달러)가 opus(4달러)의 2배인 동안은 opus subagent 가 기본이다(S10L).
- 비용 지표의 함정: 판정 토큰은 캐시에서 읽은 토큰을 빼므로, 같은 타입 · 모델의 호출이 직전 5분 안에 있었는지에 따라 첫 호출에서 캐시로 읽히는 앞부분 16,244 토큰이 판정 토큰에 들어가거나 빠진다(coder 대조 과제 5회 평균 62,971 대 77,665, 첫 호출의 프롬프트 크기는 70,120 으로 같음). 전후를 비교할 때는 이 조건을 맞춘다.
- 규칙에 effort 를 적지 않는다(S10E). medium 이 7.8% 싸고 품질 차이가 없었다는 수치는 개편 뒤 effort 작업(R5)의 입력으로 넘긴다. **(2026-11-12 §9 로 대체: 에이전트별 effort 는 `agents/*.md` 머리가 정하고 §9 가 근거를 적는다. 이 항목은 당시 결정의 이력이다.)**
- 한계: 과제 하나(소스 3 · 시험 3)의 결과다. 더 큰 변경이나 설계 선택이 갈리는 변경은 재지 않았고, 그런 일은 여전히 main 이 결정을 먼저 한다(§1).
- 독립 검수를 붙이는 까닭: 규칙을 바꾸기 전의 새 main 세션은 같은 과제를 직접 구현하고 qa · reviewer 를 한 번도 부르지 않았다. 통째로 하는 쪽은 작성자가 스스로 검수하게 되므로 다른 눈이 필요하다.
- 측정 기록: `intent/2026-11-05-agent-consolidation.md` 개정 2 «측정 결과».
- **검수 절차 원문**(2026-11-10 상시 «구현 갈래» 에서 이관): 결합도 높은 구현이 끝나면 작성자와 다른 **qa**(호출부 · 시험 · 동작)와 **reviewer**(바뀐 함수의 의도 대조, 라우팅 1.9)가 독립 검수한다. reviewer 에게는 시그니처나 동작이 바뀐 함수를 하나 지정해 넘긴다(여럿이면 바뀐 폭이 가장 큰 것부터, 더 볼지는 결과를 보고 정한다). security 병행은 라우팅 1행 그대로다. FAIL 은 같은 구현 subagent 에 SendMessage 로 돌려보내고, 두 번 돌려보내도 FAIL 이면 사용자에게 보고한다. main 이 직접 고친 결합 변경이 생겼다면 그것도 같은 검수를 받는다(직접 고쳐도 된다는 뜻이 아니다). 결정 · 사용자 합의 · 검수 결과 채택은 main 소유다.

## §8 소유권 각주 (model-assignment.md §1 에서 2026-09-15 이관, 원문 그대로)

> **아키텍처 소유권 (라우팅 5와의 관계)**: 설계안 작성·대안 비교는 planner에 위임 가능(자문) — **최종 아키텍처 결정·사용자 합의는 main 소유**. "메인 세션 직접 처리"는 결정·합의를 뜻하며 planner 자문 위임과 상충하지 않는다.
> **researcher·토론 소유권 (라우팅 6·9와의 관계)**: 실험 분석·논문 본문·설계 비판 평가는 researcher에 위임 가능(자문·초안), "검토·타당성·비교" 토론은 라우팅 9의 teammate 소집으로 진행 — 두 경우 모두 **최종 판단·사용자 합의는 main 소유** (planner 각주와 동일 원리). §1의 "사용자 합의 필요" 행은 합의 단계의 직접 수행을 뜻하며 자문·토론 위임과 상충하지 않는다. **reviewer(라우팅 1.9)도 같은 원리다**: opus 로 한 함수의 지적 목록을 내는 자문이고 결정은 사용자, 적용은 coder 다(2026-09-11).

## §9 예외 표의 근거와 경위 (`rules/model-assignment.md` § 예외 표)

| 행 | 근거 | 경위 |
|---|---|---|
| 학술 문헌 탐색 → searcher opus · high | 사용자 지정(2026-11-12, 측정값 아님) | 모델 · effort 사전 평가(`intent/2026-11-11-model-effort-evaluation.md` 개정 3)에서 인터넷 탐색 과제는 두 번의 난이도 점검 모두 가장 싼 조합(haiku · medium)도 10문항을 다 맞혀 변별이 없었다. 사용자가 그 과제를 측정에서 빼고 searcher 의 값을 직접 정했다. 기본은 sonnet · medium 이고 학술 문헌(논문 · 이론 · 수학/과학 레퍼런스)을 찾을 때는 opus · high 다 |

- 적용 대상은 문헌을 찾는 searcher 다. 인용을 검증하는 citation-verifier 는 포함하지 않는다.
- 넘기는 방법: Agent 호출의 `model: "opus"` · `effort: "high"` 인자를 쓰고 작업명 접두사는 `opus:` 로 한다. 호출 인자는 정의 파일의 `effort` 보다 우선한다(Claude Code 공식 문서 sub-agents 의 «Choose an effort level», 호출 인자는 2.1.292 이상). 호출 인자의 effort 가 실제로 적용되는 것은 2026-11-11 측정 전 시험(`fold-bench/effort-eval` 의 trial haiku-effort)에서 확인했다.
- `name` 인자를 붙여 소집하면 in-process teammate 로 떠서 호출 인자의 effort 가 적용되지 않는다. 2026-11-12 실측: `name` 을 붙인 opus · high 소집은 API effort 가 medium 이었고, `name` 없이 같은 인자로 소집하자 high 였다. 그래서 예외 행으로 소집할 때는 `name` 을 붙이지 않는다. 같은 날 정의 파일의 `effort: medium` 으로 기본 소집이 sonnet · medium 으로 도는 것도 확인했다. `name` 이 떨어뜨리는 것은 호출 인자의 effort 뿐이다. 같은 날 `name` 을 붙이고 호출 인자 없이 소집한 scout 는 정의 파일의 값대로 haiku · high 로 돌았다(서브에이전트 기록의 적용 effort 값). 그래서 /discuss 의 teammate 도 정의 파일의 effort 를 받는다.
- 정의 파일 머리의 `effort` 키: 값은 low · medium · high · xhigh · max 다. 생략하면 메인과 다른 모델의 서브에이전트는 그 모델의 저장된 값이나 기본값으로 돈다(같은 문서, 2.1.317 변경).

### 에이전트 기본 effort (2026-11-12 사용자 결정)

| 에이전트 | 모델 · effort |
|---|---|
| planner · researcher · reviewer | opus · high |
| tutor | opus · medium |
| coder | sonnet · high |
| qa · security | sonnet · high |
| citation-verifier | sonnet · medium |
| scout | haiku · high |
| docs · gitops | sonnet · medium |
| searcher | sonnet · medium (학술 문헌 탐색은 opus · high, 위 예외 행) |

- 왜 전부 명시하는가: 세션의 effort 는 main 과 같은 모델인 서브에이전트에만 적용된다. 다른 모델이면 그 모델의 기본값으로 도는데 공식 문서 기준 Opus · Sonnet · Haiku 5.5 모두 medium 이다. 그래서 정의 파일에 적지 않으면 전부 medium 이었다.
- 호출 때 모델만 올려 부르면(예: 결합도 높은 구현의 coder 를 opus 로) 정의 파일의 effort 가 그대로 따라간다. 2026-11-12 실측: 정의를 고친 같은 세션에서 scout 는 haiku · high, planner 는 opus · high, 모델만 opus 로 올린 coder 는 opus · high 로 돌았다(서브에이전트 기록의 적용 effort 값).
- 근거: 측정(fold-bench/effort-eval)은 과제 5개 중 1개만 조합을 갈라 2026-11-12 에 닫았다. 값은 공식 문서와 운영 기록으로 사용자가 정했다. 문서 요지는 세 가지다.
  - Claude Code 모델 설정 문서: medium 은 범위가 분명한 일상 구현에 두고 high 는 검증이 중요하거나 경계 사례가 많은 일(기존 코드의 버그 수정)에 둔다.
  - API 의 effort 안내: high 는 복잡한 추론과 어려운 코딩에 두고 Haiku 5.5 의 low 는 검색 건너뜀과 조기 종료 위험이 있다고 적는다.
  - 모델 선택 안내: effort 조정을 모델 교체보다 먼저 쓸 수단으로 둔다.
  - URL: code.claude.com/docs/en/model-config , platform.claude.com/docs/en/build-with-claude/effort , platform.claude.com/docs/en/about-claude/models/choosing-a-model , code.claude.com/docs/en/sub-agents
- 남는 한계: opus 의 medium 대 high 와 sonnet 의 medium 대 high 는 재지 않았다. scout 의 high 는 문서에 직접 근거가 없는 사용자 선택이다. coder 를 high 로 올린 근거 가운데 하나인 실패 기록(최근 30일 «구현 정확성» 15건)은 원인 분석이 안 되어 있다.
- 경위 상세: `docs/superpowers/plans/2026-11-11-model-effort-evaluation.md` «개정 4».

### FAIL 뒤 올리는 기준 (2026-11-24 사용자 결정, 의뢰서 W8)

- 정본은 `rules-lazy/qa-process.md` § 계획-대비 검수의 «FAIL 원인별 격상 순서» 다. 요약: 1) 지시문 기록으로 맥락 누락부터 점검하고 누락이면 지시문을 보완해 같은 모델로 다시 맡긴다 2) 누락이 아닌데 결과가 틀렸으면 모델을 올린다 3) 누락이 아닌데 단계를 건너뛰었으면 effort 를 올린다.
- 올릴 때는 위 예외 표와 같이 Agent 호출 인자 `model` · `effort` 로 넘기고 `name` 은 붙이지 않는다. 두 번 뒤에도 FAIL 이면 사용자에게 보고한다.
- 원인 분류는 판단이라 기계로 집행하지 않는다.
- 근거: Anthropic 공식 글 «모델과 effort 선택»(2026-07-07)의 정독 요약(2026-11-24 하네스 점검 때 searcher 가 읽고 돌려준 요약: «틀리면 더 큰 모델, 건너뛰거나 중도 포기면 effort, 그 전에 맥락부터 점검»). 외부 글의 요약이라 참고 자료다.
