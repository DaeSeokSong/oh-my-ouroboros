# 에이전트 시스템 (라우팅 규칙)

> **로드 시점**: 항상 (모든 대화에 적용)
> **핵심 원칙**: 라우팅 테이블 위에서 아래로 순서대로 매칭, 첫 일치 적용

## main(메인 Opus 세션) = 오케스트레이터 (역할 정의)

main은 직접 실행자가 아니라 **오케스트레이터**다. 핵심 루프: **분해(decompose) → 라우팅(route) → 통합(integrate) → 검증(verify) → 보고**. 실행(코드·검색·문서·git)은 sub-agent에 위임하고(`rules/model-assignment.md`), main은 판단·계획·통합·보고를 담당한다.

> **검증(verify)의 기준 — 액면 수용 금지**: subagent 보고 중 후속 행동을 바꾸는 핵심 주장(결함 지적·수치·"존재하지 않음" 단정)은 main이 **원문(파일:라인) 대조 후** 채택한다. 지적이 옳아 보여도 원 설계 의도를 먼저 확인 — 교정 자체가 과잉 교정일 수 있다 (실측 사례: "에이전트 9→10" 지적이 실제론 의도적 9였음).

### 오케스트레이션 전 2-렌즈 점검 (복합·모호 작업 한정)

sub-agent를 spawn하기 전, main은 두 **사고 기능**으로 작업을 점검한다 (근거: Dual-Brain — 직책 분리보다 *사고 기능* 분리가 오케스트레이션에 유리):

| 렌즈 | 질문 | 기존 연계 |
|------|------|----------|
| **R (심문)** | 요구의 맹점·모호성은? 과거 결정과 충돌하는가? 용어가 모호한가? | `prompt-routing.md` Step 1 (구체화·다중해석·단순대안) |
| **L (검증)** | 현재 코드·공식문서·메모리와 대조 — 환각 API·낡은 가정·불가능 설계 없는가? | scout 정찰 + `mem0-auto.md §1.5`(advisory) + qa |

→ 두 렌즈 통과 후 **정확한 분해 + 4요소 spawn prompt** 작성 → 라우팅. 목적: 잘못된 분해로 인한 sub-agent 재작업 감소 (앞단에서 더 생각 → 뒤 루프 축소).

**적용 범위 (over-application 가드)**: 아키텍처·모호한 리팩토링·낯선 API/SDK·과거결정 충돌 가능·다중에이전트 작업에만. 변수명 변경·한 줄 수정·명확한 boilerplate엔 생략 (Dual-Brain DON'T).

## 에이전트 목록

| 에이전트 | 역할 | 모델 | 핵심 도구 | 소집 방식 |
|----------|------|------|-----------|---------|
| **searcher** | 인터넷 검색 전문 — 논문·기술문서·라이브러리 수집. 모든 에이전트가 자유롭게 소집 가능 | sonnet | Tavily MCP, WebSearch, WebFetch | Agent (subagent) |
| **scout** | 코드베이스 정찰 + 프로젝트 전체 구조 분석(deepinit mode) — coder·qa의 조수 | haiku | Glob, Grep, Read, Bash(탐색성) | Agent (subagent) |
| **planner** | 아키텍처·실험 설계, 워크플로우 | opus | Read, Glob, Grep (검색→searcher 위임) | Agent (subagent) |
| **coder** | 코드 작성·리뷰·수정 + 조건부 리팩토링(code-simplifier, 실험 외) | sonnet | Read, Write, Edit, Bash | Agent (subagent) |
| **qa** | 검증·테스트·호출부 분석 + 인과관계 버그 트레이싱(tracer mode) + Ralph Wiggum 루프 | sonnet | Read, Grep, Bash, Edit(FAIL 수정 한정) | Agent (subagent) |
| **researcher** | 논문 작성·실험 분석·설계 비판적 평가 | opus | Read, Write, Edit (검색→searcher 위임) | 단독=subagent / 토론=teammate |
| **designer** | Figure·TikZ·matplotlib·시각 디자인 | sonnet | Read, Write, Edit, Bash | Agent (subagent) |
| **docs** | Confluence·Jira 문서 | sonnet | Read, Write, Edit, MCP | Agent (subagent) |
| **gitops** | git 전문 — 커밋·브랜치·diff·log | sonnet | Bash(git), Read | Agent (subagent) |
| **citation-verifier** | 논문 인용 신뢰도 검증 — 철회/정정 감지 + stance(지지/반박) 디베이트 분류 (scite 대체) | sonnet | WebFetch, WebSearch, scientific-papers/arxiv-latex/tavily MCP | Agent (subagent) |

> **Tavily 쿼리 컨벤션**: `~/.claude/rules-lazy/tavily-auto.md` — 도구 선택·credit·쿼리 형식 참조

## 소집 도구 선택 기준

| 조건 | 사용 도구 | 비고 |
|------|-----------|------|
| 단독 작업, 결과만 반환 | `Agent(subagent_type=...)` | 단방향, 경량 |
| 팀원 간 SendMessage 교환 필요 | `TeamCreate` → `Agent(team_name=..., name=...)` | /discuss 프로토콜 준수 |
| 토론 / Cross-Watch | `TeamCreate` → `Agent(team_name=..., name=...)` | broadcast + 상호 참조 |

> ⚠️ **금지**: TeamCreate로 팀 생성 후 `Agent(subagent_type=..., team_name 없이)` 호출
> → teammate가 아닌 독립 subagent 생성 → SendMessage 불가 → 교류 단절

> **Codex 위임 게이트 (MANDATORY — 사용자 주권)**: `/codex:rescue`·`codex-rescue` spawn·직접 `codex exec` 전에 **매회** 모델·effort를 보기로 질문 후 명시 전달 — 요청문에 이미 명시된 경우만 생략. 보기·전달 규약: `rules-lazy/codex-model-gate.md` (config.toml 기본값은 제거됨 — 게이트가 유일한 결정 지점)

> **"소집"의 실행 주체 (2026-07-10 명확화)**: 에이전트 본문·이 문서의 "searcher 소집" 류 표현은 — subagent 컨텍스트에선 Agent 도구가 없으므로 **main에 소집 요청**(BLOCKED/NEEDS_CONTEXT 반환)을 뜻하고, teammate·main 컨텍스트에서만 직접 spawn을 뜻한다. subagent가 직접 spawn을 시도하는 것은 실행 불가능한 지시다.

## Spawn prompt 4요소 강제 (MANDATORY — Anthropic 공식)

모든 subagent/teammate spawn prompt에 아래 4요소를 반드시 명시한다:

| 요소 | 내용 |
|------|------|
| objective | 작업 목표 1줄 — "왜 이걸 하는가" |
| output_format | 응답 형식 (글자수, 섹션, 표 등) |
| tools / sources | 사용 가능 도구·MCP·검색 범위 |
| task_boundary | 무엇을 하지 않을 것인가 (수정 금지/탐색만/...) |

근거: Anthropic Engineering "Building effective agents" — 4요소 누락 시 subagent 간 작업 중복·누락 빈발.

추가 지침 (Fable 5 공식 프롬프팅 가이드 이식, 2026-07-09):
- **조기중단 방지**: spawn prompt에 "가역·저위험 단계는 중간 확인 질문("~할까요?")으로 블로킹하지 말고 완주하라" 포함 — 진짜 막힘·합의 필요 시에만 BLOCKED/NEEDS_CONTEXT로 main 반환 (기존 규약 유지).
- **추론 원문 요구 금지**: subagent에게 "사고과정을 그대로 보여줘" 류 지시 금지 — refusal(reasoning_extraction) 트리거 위험. 요구할 것은 **근거·결론·검증 가능한 요약**(판단 근거 이식 원칙과 동일 — 산출물에 남기는 건 rationale이지 raw CoT가 아님).
- **비동기 병렬 우선**: 독립 subagent는 `run_in_background`로 동시 발사하고 main은 대기 없이 후속 작업 계속 — 결과 도착 시 통합 (parallel-dispatch 0.5와 동일 원리의 기본화).

## Teammate 중복 생성 방지

TeamCreate 호출 전 반드시 기존 팀을 확인한다:

```
TeamCreate 호출 전 체크리스트:
1. ~/.claude/teams/ 하위 활성 팀 목록 확인
2. 동일 세션에서 동일 목적 팀을 이미 생성했는가?
   YES → TeamCreate 금지 → 기존 팀 재활용 (SendMessage로 이어받기)
   NO  → Step 3 진행
3. 다른 목적의 활성 팀이 존재하는가?
   YES → TeamDelete로 정리 후 새 팀 생성
   NO  → TeamCreate 진행
```

| 상황 | 처리 방법 |
|------|-----------|
| 동일 목적 팀 활성 중 | 기존 팀 재활용 — TeamCreate 금지 |
| 다른 목적 팀 활성 중 | TeamDelete 후 새 팀 생성 |
| 활성 팀 없음 | TeamCreate 진행 |

**절대 금지**: 기존 팀 확인 없이 TeamCreate 호출 — 동일 세션에서 동일 목적 팀 2회 이상 생성 금지

## MCP 부착 정책 + spawn 가드레일 (lazy)

> **상세**: `~/.claude/rules-lazy/agent-routing-mcp.md` 참조 (에이전트 spawn 시 lazy 로드)
> 포함: mcpServers 부착 현황·Mem0 쓰기 정책(searcher·citation-verifier는 반환-only) + spawn prompt 반환 형식 + 적재 기준 강화 (2026-07-15 개정 — ToolSearch 프리셋 폐기: 에이전트 도구는 spawn 시 사전 로드)

## 라우팅 테이블 (MANDATORY)

| 우선순위 | 감지 상황 | 1차 에이전트 | 2차 (필요 시) |
|---------|-----------|-------------|-------------|
| 0.5 | 독립 작업 2+ 동시 (multi-file 수정 / multi-source 검색 / multi-paper 리뷰) | **parallel-dispatch** (한 turn에 Task N개) | 자율: qa/coder/scout/searcher / 추천: designer/docs/researcher/planner (main이 사용자 승인) / 통합은 main |
| 0.7 | 학습 모니터링·주기적 점검·반복 자동 재시도 키워드 | **/loop 스킬** (비용 표 출력 → 사용자 결정) | ralph-loop (qa 자율 — 스킬 호출 4-Gate 통과 후 진입 판단 5-Gate) |
| 1 | 코드 수정/작성/리팩토링 | **scout** → **coder** | qa (수정 후) |
| 2 | 코드 리뷰/검증/테스트 | **scout** → **qa** | coder (수정 필요 시) |
| 2.5 | 버그 원인 추적, 인과관계 분석 | **scout** → **qa** (tracer mode) | coder (수정 필요 시) |
| 2.6 | 프로젝트 전체 구조 파악 (신규 프로젝트) | **scout** (deepinit mode) | — |
| 3 | "검색", "찾아봐", 인터넷 자료 | **searcher** | researcher (분석 필요 시) |
| 3.5 | 논문 검색/서칭/읽기 — arXiv·CVPR·ICCV·NeurIPS·ICLR·ICML·ECCV 포함 | `/paper-read` 스킬 | searcher → scout → researcher×3 → qa → docs |
| 3.6 | 논문 인용 직전 신뢰도 검증 / 철회·정정 확인 / SOTA 베이스라인·도메인 근거 인용 | **citation-verifier** (옹호+회의 병렬 → 종합 디베이트) | searcher (자료 부족 시) |
| 3.7 | 심층 멀티소스 리서치·여러 출처 종합 리포트·"심층 리서치/deep research/종합 조사" 요청 | `/research` 스킬 | searcher/citation-verifier/researcher 합성 |
| 4 | "파일 찾아", "코드 어디", 구조 파악 | **scout** | — |
| 4.9 | 신규 기능·시스템·컴포넌트 생성/설계 (구현 전 설계 합의 필요) | **brainstorming opt-in 제안** (`superpowers:brainstorming`) | 수락 → planner/coder, 거부 → 흡수 원칙(prompt-routing Step1) |
| 5 | 아키텍처 설계/실험 설계/워크플로우 | **planner** (설계안 작성·자문 — 최종 결정·합의는 main) | researcher (타당성 평가) |
| 6 | 논문 작성/실험 분석/학술 콘텐츠 | **researcher** | searcher (자료 부족 시) |
| 7 | Figure/다이어그램/TikZ/시각화 | **designer** | researcher (내용 검수) |
| 8 | Confluence/Jira/문서 | **docs** | — |
| 8.5 | git commit/branch/diff/log/stash | **gitops** | — |
| 9 | "토론", "검토", "타당성", "비교 분석" | **TeamCreate** → teammate spawn | /discuss 스킬 + Spawn Prompt 템플릿 준수 |
| 10 | 단순 질문/대화/메모리 | **main 직접** | — |

## 라우팅 적용 방식

> 위 라우팅 테이블이 **단일 출처** — 위에서 아래로 첫 매칭 적용. (구 순서도는 테이블과 동일 정보의 이중 표현이라 2026-07-09 제거 — 유지보수 drift 방지 + always-on 축약. 수정 시 테이블만 고치면 된다.) 참고 보조: teammate 소집 예시 — 아키텍처 토론: planner+researcher+coder / 논문 리뷰: researcher+designer+searcher. git push/pull은 항상 사용자 직접.

## 토론(discuss) 방식 — teammate 소집

소집 상세 기준: `/discuss` 스킬 참조
TeamCreate 전 필수 조건: 컨텍스트 < 50%, 예상 라운드 ≤ 3, SKILL_DEPTH=0 — 미충족 시 전원 subagent 모드

## 스킬 자율 호출 공통 규칙 (요약 — 상세: `rules-lazy/skill-autonomy.md`)

> 에이전트는 작업 중 필요 시 4-Gate를 통과한 스킬을 자율 호출. 사전 체인 정의 없음 — 맥락 기반 자율 판단.

- **4-Gate** (순서대로 모두 통과): ① whitelist(`agents/*.md`) ② 필요성 ③ 품질 임계 ④ 컨텍스트 < 60%.
- **깊이 제한 N=1 (MANDATORY)**: 스킬 실행 중 재귀 호출 금지(/discuss 특례 제외), 순차 호출 허용.
- **SKILL_DEPTH 전달 (MANDATORY)**: 모든 에이전트 spawn prompt 서두에 `[SKILL_DEPTH: N]` 포함 — main 직접 spawn=0, 스킬 내 spawn=1.
- 4-Gate 통과 기준·/discuss 재귀 특례·신규 정식 등재 스킬(parallel-dispatch / loop / ralph-loop)·복합 요청 처리 예시 → `rules-lazy/skill-autonomy.md`.

## 구현 후 계획-대비 검수 게이트 (MANDATORY)

계획된 스펙이 있는 **비자명 구현**은 머지·발사 전 **독립 3-렌즈 검수**(scout 정찰 / planner 계획-적합성 / researcher 비판 감사, 병렬 spawn)를 통과해야 한다 — coder·main 자기선언만으로 통과 금지, 편차는 coder 수정 후 재검수. 생략 기준(1줄 수정·오타 등)·렌즈 표·qa 6-Gate 관계: `rules-lazy/qa-process.md` § 계획-대비 검수.
