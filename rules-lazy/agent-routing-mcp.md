# 에이전트 시스템 — MCP 부착 정책 + spawn 가드레일 (lazy)

> **로드 시점**: 에이전트 spawn 직전 (subagent/teammate 호출 시)
> **상위 파일**: `~/.claude/rules/agent-routing.md`

## 라우팅 표 행 각주 경위·실측 (agent-routing.md 이관)

- **3.75 행 우선순위 경위**: 2026-09-02 Grok 검수 A6 — 한 행에 quiz 와 explain 이 같이 있어 «다시 설명해줘»가 quiz 로 새던 문제를 3.8보다 좁은 트리거로 분리해 막았다.
- **0.5 행 논문 예외 근거**: 2026-08-25 결정 — 논문 검색·읽기·리뷰는 편수 무관 3.5로 고정해 필수 3인 검수·선별·퀴즈 우회를 방지한다.
- **"표 적용 전 탈출" 실측**: 14일 58건 중 12%가 `general-purpose` 등 표 밖 타입으로 소집되어 있었다 — 표의 에이전트 이름만 쓰도록 재확인한 근거.
- **"소집"의 실행 주체 근거 (2026-07-10)**: subagent 컨텍스트엔 Agent 도구가 없어 spawn이 물리적으로 불가능하다 — 그래서 "소집"은 main에 대한 요청(BLOCKED/NEEDS_CONTEXT)으로만 성립한다.
- **검증 액면 수용 금지의 실측 사례**: `skills/harness-audit/SKILL.md` Step 7에서 subagent 지적이 옳아 보였지만 원 설계 의도를 확인하니 과잉 교정이었다. 이 사례는 `rules/agent-routing.md` 「검증(verify)의 기준」 문단의 근거다.

## 오케스트레이션 전 2-렌즈 점검 (agent-routing.md 이관 — 복합·모호 작업 한정)

sub-agent를 spawn하기 전, main은 두 **사고 기능**으로 작업을 점검한다 (근거: Dual-Brain — 직책 분리보다 *사고 기능* 분리가 오케스트레이션에 유리):

| 렌즈 | 질문 | 기존 연계 |
|------|------|----------|
| **R (심문)** | 요구의 맹점·모호성은? 과거 결정과 충돌하는가? 용어가 모호한가? | `prompt-routing.md` Step 1 (구체화·다중해석·단순대안) |
| **L (검증)** | 현재 코드·공식문서·메모리와 대조 — 환각 API·낡은 가정·불가능 설계 없는가? | scout 정찰 + `mem0-auto.md §1.5`(advisory) + qa |

→ 두 렌즈 통과 후 **정확한 분해 + 4요소 spawn prompt** 작성 → 라우팅. 목적: 잘못된 분해로 인한 sub-agent 재작업 감소 (앞단에서 더 생각 → 뒤 루프 축소).

**적용 범위 (over-application 가드)**: 아키텍처·모호한 리팩토링·낯선 API/SDK·과거결정 충돌 가능·다중에이전트 작업에만. 변수명 변경·한 줄 수정·명확한 boilerplate엔 생략 (Dual-Brain DON'T).

## Spawn prompt 4요소 강제 (agent-routing.md 이관 — MANDATORY — Anthropic 공식)

모든 subagent/teammate spawn prompt에 아래 4요소를 반드시 명시한다:

| 요소 | 내용 |
|------|------|
| objective | 작업 목표 1줄 — "왜 이걸 하는가" |
| output_format | 응답 형식 (글자수, 섹션, 표 등) |
| tools / sources | 사용 가능 도구·MCP·검색 범위 |
| task_boundary | 무엇을 하지 않을 것인가 (수정 금지/탐색만/...). 표준 문구 1개는 항상 포함: 다른 저장소는 읽기만, 수정 금지(프로젝트 경계 — `rules/code-execution.md`) |

근거: Anthropic "Building effective agents" — 누락 시 작업 중복·누락 빈발.

> **output_format 표준 문구 (MANDATORY)**: 모든 spawn prompt의 output_format에 "최종 보고의 마지막 text 블록 안에 행두 `RESULT: <값>` 한 줄"을 포함한다. 값은 `PASS|DONE|DONE_WITH_CONCERNS|FAIL|BLOCKED|NEEDS_CONTEXT|REJECT` 중 첫 토큰, 굵게·따옴표·코드펜스·번호 항목 안 금지 — 상세: `agents/coder.md` § 수정 완료 후.

## Teammate 중복 생성 방지 (agent-routing.md 이관)

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

## SendMessage 전 ListAgents 확인 (MANDATORY — 2026-08-10 사용자 지시)

> **경계 (사용자 확정)**: "모든 SendMessage 직전"이 아니라 **main 세션 밖과 소통**하는 경우로 한정 — teammate·subagent·타 세션(로컬/클라우드/원격 브릿지)에 메시지를 보내는 SendMessage 호출 직전. 방금 spawn해 agentId를 이미 반환받은 대상도 포함(주소 확인의 목적은 "존재 확인"이지 "이번 턴 신규 생성분 제외"가 아니다).
> **제외**: Agent()의 백그라운드 자동 알림(task-notification)을 수동적으로 기다리는 경우 — SendMessage를 능동적으로 조립·발신하는 시점만 대상.

- **절차**: SendMessage 호출 직전 `ListAgents`로 현재 주소 가능한 이름 목록을 확인 → 정확한 `to` 값을 그 목록에서 그대로 복사해 사용한다(이름을 기억이나 추정으로 재구성하지 않는다).
- **한 턴 내 중복 호출 방지**: 같은 턴에서 이미 ListAgents를 호출해 목록을 확보했으면(직전 spawn 직후 등) 재호출하지 않고 그 결과를 재사용한다.
- **판단 근거**: SendMessage는 이름 문자열로 대상을 특정하는 도구라 이름이 조금이라도 어긋나면(리네임·중복 접미사·세션 재시작으로 실제 활성 이름이 바뀐 경우) 조용히 오발신되거나 실패한다. ListAgents 선행이 이 실패 모드를 원천 차단한다.
- **연계**: `rules/agent-routing.md` § Teammate 중복 생성 방지(TeamCreate 전 팀 확인)와 같은 계열의 "발신 전 실재 확인" 원칙 — 팀은 TeamCreate 전에, 개별 대상은 SendMessage 전에 확인한다.

## Spawn prompt 추가 지침 (Fable 5 공식 프롬프팅 가이드 이식, 2026-07-09 — 4요소에 더해)

- **조기중단 방지**: spawn prompt에 "가역·저위험 단계는 중간 확인 질문("~할까요?")으로 블로킹하지 말고 완주하라" 포함 — 진짜 막힘·합의 필요 시에만 BLOCKED/NEEDS_CONTEXT로 main 반환 (기존 규약 유지).
- **추론 원문 요구 금지**: subagent에게 "사고과정을 그대로 보여줘" 류 지시 금지 — refusal(reasoning_extraction) 트리거 위험. 요구할 것은 **근거·결론·검증 가능한 요약**(판단 근거 이식 원칙과 동일 — 산출물에 남기는 건 rationale이지 raw CoT가 아님).
- **병렬은 foreground 동시 발사가 기본**: 독립 subagent N개는 **한 응답에 복수 tool_use로 동시 발사**(동시 실행 + 알림 턴 0 — qa∥security 병행도 이 방식). `run_in_background`는 상위 정본(`notification-turn-reduction.md` § 알림 턴 물리적 감축 1항)의 예외 조건 — 사용자 병렬 명시 또는 수십 분급 장기 작업 — 에서만 사용한다 (Codex 2026-07-31 2차: 종전 "background 우선" 표현이 상위와 충돌 → 전면 정렬).

## MCP 도구 로딩의 실제 메커니즘 (2026-07-15 전면 개정 — GPT 교차감사 P1-1)

에이전트의 MCP 도구는 `agents/*.md` frontmatter의 **`mcpServers:` 필드가 결정**하며, 부착된
서버의 도구 스키마는 **spawn 시 이미 로드**되어 있다 (Claude Code 2.1.210 실측, 확인일 2026-10-17 기준 Claude Code 2.1.301 —
`knowledge/harness/mcpservers-bypass-tools-allowlist.md`). 서브에이전트 컨텍스트에는
ToolSearch가 주입되지 않으므로, 종전의 "spawn 시 ToolSearch 프리셋 일괄 로드" 체계는
**수행 불가능한 죽은 지시였다 — 전면 폐기**. main이 spawn prompt에 ToolSearch 쿼리를
넣어서도 안 된다 (에이전트가 실행 불가).

> (참고: ToolSearch가 유효한 곳은 **main 세션**뿐 — main의 deferred MCP 도구는 종전대로
> `ToolSearch("select:...")` 로드 필요, `rules/mem0-auto.md` §0)

### 에이전트 spawn prompt 서두에 포함할 2가지

1. `[SKILL_DEPTH: N]` 마커 (기존 규칙)
2. MCP 가용 상태 — **미연결이 확인된 경우에만** `[MEM0: unavailable]` 식으로 표시
   (`mcp-fallback.md` 참조. OAuth 커넥터(Atlassian 등)는 headless/subagent에서 부재 가능)

### 에이전트별 mcpServers 부착 현황 + Mem0 쓰기 정책 (2026-07-15 실측)

| 에이전트 | 부착 서버 (frontmatter) | Mem0 정책 |
|---------|------------------------|-----------|
| searcher | tavily, scientific-papers, arxiv-latex-mcp, context7 | **미부착 + disallowedTools deny** — untrusted 격리, T22 payload 반환 → main 저장 |
| citation-verifier | scientific-papers, arxiv-latex-mcp, pubmed, openreview, tavily | **미부착 + disallowedTools deny** — T21 payload 반환 → main 저장 |
| coder / planner | context7, mem0 | 저장·검색 가능 (trusted 콘텐츠 대상) |
| researcher | mem0 | 저장·검색·갱신 가능 |
| qa / gitops / designer / scout / reviewer | mem0 | 저장·검색 위주 (reviewer 는 과거 QA 이력 검색 위주) |
| docs | claude_ai_Atlassian, mem0 | 저장·검색 가능 (Confluence 쓰기는 사용자 승인 게이트) |

> **update_memory 주체**: planner/researcher만 (3팀 Round 2 합의 + B4 중복 방지 — searcher는 2026-07-15 Mem0 제거로 대상 제외)
> **untrusted 격리 원칙**: 외부 공개 콘텐츠를 읽는 에이전트는 영속 메모리에 직접 쓰지 않는다 — `untrusted-quarantine.md` MCP 쓰기 금지 목록(Mem0 포함) 참조

### 미연결 처리
에이전트가 부착된 서버의 도구를 목록에서 찾지 못하면(OAuth 미연결·버전 회귀 등) 해당 MCP를 unavailable로 간주하고 BLOCKED로 main 보고 → main이 spawn prompt에 `[MEM0: unavailable]` 등 표시 후 재시도 또는 `mcp-fallback.md` 규칙 적용

## 에이전트 spawn prompt 반환 형식 가드레일 (MANDATORY)

모든 spawn prompt 에 반환 형식 제약 3줄을 넣는다. 반환 길이·적재 기준(100자·1500자·Write 없는 에이전트 예외)과 3줄 본문은 `rules-lazy/token-efficiency.md` § Subagent 반환값 적재 최소화 · § Agent Spawn Prompt 가드레일이 단일 정본이다.
