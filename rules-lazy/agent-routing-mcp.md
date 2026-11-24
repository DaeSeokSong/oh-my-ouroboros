# 에이전트 시스템 — MCP 부착 정책 + spawn 가드레일 (lazy)

> **로드 시점**: 에이전트 spawn 직전 (subagent/teammate 호출 시)
> **상위 파일**: `~/.claude/rules/agent-routing.md`

## 라우팅 표 행 각주 경위·실측 (agent-routing.md 이관)

- **3.75 행 우선순위 경위**: 2026-09-02 Grok 검수 A6 — 한 행에 quiz 와 explain 이 같이 있어 «다시 설명해줘»가 quiz 로 새던 문제를 3.8보다 좁은 트리거로 분리해 막았다.
- **0.5 행 논문 예외 근거**: 2026-08-25 결정 — 논문 검색·읽기·리뷰는 편수 무관 3.5로 고정해 필수 3인 검수·선별·퀴즈 우회를 방지한다.
- **"표 적용 전 탈출" 실측**: 14일 58건 중 12%가 `general-purpose` 등 표 밖 타입으로 소집되어 있었다 — 표의 에이전트 이름만 쓰도록 재확인한 근거.
- **"소집"의 실행 주체 근거 (2026-07-10)**: subagent 컨텍스트엔 Agent 도구가 없어 spawn이 물리적으로 불가능하다 — 그래서 "소집"은 main에 대한 요청(BLOCKED/NEEDS_CONTEXT)으로만 성립한다.
- **검증 액면 수용 금지의 실측 사례**: `skills/harness-audit/SKILL.md` Step 7에서 subagent 지적이 옳아 보였지만 원 설계 의도를 확인하니 과잉 교정이었다. 이 사례는 `rules/agent-routing.md` 「검증(verify)의 기준」 문단의 근거다.
- **4.85 선행 규칙(«어느 행이든 비자명 작업은 `/intent` 가 먼저», 병렬 발사 0.5 포함)**: 2026-10-02 사용자 결정(2026-11-10 상시 표 머리에서 날짜 이관).
- **1.9 행 위치 경위**: 2행(코드 리뷰/검증)보다 좁은 트리거라 위에 둔다(2026-11-10 상시 칸에서 이관).
- **표 밖 타입 차단 훅 (2026-11-09 에이전트 정리 4단계 채택)**: 표 밖 타입 소집은 PreToolUse 훅 `scripts/agent-type-gate.py` 가 막는다. 훅 등록은 사용자가 한다. graphify 예외는 내용이 active 인 30분 안의 표지 파일과 `graphify extract` 설명이 함께 있을 때만 통과한다. 이 예외는 표 밖 타입 전반을 허용하지 않는다. 훅 허용 목록에는 표의 12종 외에 Codex 위임 경로, code-simplifier, claude-security 접두의 플러그인 에이전트가 더 있다(2026-11-10 상시 «라우팅 적용 방식» 에서 이관).

## 에이전트를 따로 두는 기준 (2026-11-24 사용자 결정, 의뢰서 `intent/2026-11-24-harness-review-six-items.md` W15)

에이전트는 맥락 격리 · 도구 권한 분리 · 병렬 실행 · 모델 단가 차이 가운데 하나 이상이 필요할 때만 따로 둔다. 직무 이름(기획자 · 개발자 · 디자이너 같은 조직도)을 본떠 늘리지 않는다. 절차와 지식만 다르면 스킬로 만든다.

- **근거 글**: «Building agents: When to fold subagents into your main agent loop»(claude.com 공식 글 · 2026-10-22 · `https://claude.com/blog/building-agents-when-to-fold-subagents-into-your-main-agent-loop`). 글이 드는 까닭은 세 가지다. 1) 단일 루프에서 맥락이 불어 품질이 측정될 만큼 떨어질 때 2) 버려도 되는 새 맥락으로 병렬 실행할 때 3) 도구 선택이 어렵거나 지시가 충돌할 때. 글은 팀이나 문제 유형별로 나누면 조직도를 복제하게 된다고(콘웨이 법칙) 경고한다.
- **하네스 자체 기준**: 글에 없고 하네스가 더한 두 까닭이다. 도구 권한 분리는 외부 글을 읽는 쪽에 쓰기를 주지 않기 위함이고 모델 단가 차이는 일의 난이도에 맞춰 모델을 달리 쓰기 위함이다.
- **신설 절차**: 에이전트를 새로 만들기 전에 위 네 가지(맥락 격리 · 도구 권한 분리 · 병렬 실행 · 모델 단가) 가운데 어느 것에 해당하는지 적는다. 해당이 없으면 스킬로 만든다.
- **현황**: 2026-11-24 기준 기존 에이전트의 통합 후보 조사가 진행 중이다.

## 새 세션 금지 실측·예외 범위 (agent-routing.md 이관)

`rules/agent-routing.md` «새 세션에 일 맡기기 금지» 의 지시일·실측·예외 범위 원문이다(2026-11-10 상시 다이어트로 이관). main 이 `claude --bg` 로 측정 세션을 만들기 직전에 이 절을 열어 범위를 대조한다. 아래 두 예외는 모두 종료됐고 2026-11-12 현재 열린 예외는 없다(절은 이력으로 남긴다).

- **지시**: 2026-11-02 사용자 지시. 의뢰서: `intent/2026-11-02-no-work-in-spare-sessions.md`.
- **실측(11-02)**: 세션이 늘어 보인 원인은 데몬이 배정한 빈 세션이 하네스 변경 알림을 첫 지시로 받아 깨어난 것(18세션)이다. harness-mod 는 첫 지시 전 세션에 알림을 넣지 않는다.
- **예외 범위(2026-11-06 사용자 결정 O1)**: 에이전트 정리(`intent/2026-11-05-agent-consolidation.md`) 6·7·9·10단계 «행동 확인»(8회와 되돌린 단계의 재측정, P1)과 4단계 후보 «name: Explore 덮어쓰기» 실제 동작 확인 1회(2026-11-07 E1, 테스트 폴더 프로젝트 레벨 정의) · 4단계 F7 측정(훅 없는 세 방식 × 3회, 2026-11-09 F4A)에 한해 main 이 `claude --bg` 로 측정 세션을 만든다. 측정이 끝나면 그 세션을 닫는다. **종료**: 측정 단계는 2026-11-10 에 전부 닫혔다.
- **예외 범위 추가(2026-11-11 사용자 결정, 비용 상한 130달러 승인)**: 모델 · effort 사전 평가(`intent/2026-11-11-model-effort-evaluation.md`, 계획 `docs/superpowers/plans/2026-11-11-model-effort-evaluation.md`)의 측정에 한해 하네스 매니저 세션의 main 이 회차마다 측정 세션 1개를 sonnet 메인으로 만든다(띄우는 명령은 `fold-bench/effort-eval/config.json` 의 `session_command`). 범위는 본 측정 126회 · 낮은 모델 확인 회차 · 무효와 바깥 사정으로 인한 재측정 · 본 측정 전 시험(메인 모델 · haiku 의 effort · 계획 확정 훅 통과 · 설계 과제 구현자 보정)이다. 측정 세션은 대상 서브에이전트 소집만 한다. 누적 금액이 상한에 닿으면 멈추고 사용자에게 묻는다. 측정이 끝나면 만든 세션의 목록(id · 시각 · 용도)을 사용자에게 보고하고, 지울지는 사용자가 정한다. **종료**: 모델 · effort 사전 평가는 2026-11-12 에 끝났다.

## 오케스트레이션 전 2-렌즈 점검 (agent-routing.md 이관 — 복합·모호 작업 한정)

sub-agent를 spawn하기 전, main은 두 **사고 기능**으로 작업을 점검한다 (근거: Dual-Brain — 직책 분리보다 *사고 기능* 분리가 오케스트레이션에 유리):

| 렌즈 | 질문 | 기존 연계 |
|------|------|----------|
| **R (심문)** | 요구의 맹점·모호성은? 과거 결정과 충돌하는가? 용어가 모호한가? | `prompt-routing.md` Step 1 (구체화·다중해석·단순대안) |
| **L (검증)** | 현재 코드·공식문서·메모리와 대조 — 환각 API·낡은 가정·불가능 설계 없는가? | scout 정찰 + `mem0-auto.md §1.5`(advisory) + qa |

→ 두 렌즈 통과 후 **정확한 분해 + 5요소 spawn prompt** 작성 → 라우팅. 목적: 잘못된 분해로 인한 sub-agent 재작업 감소 (앞단에서 더 생각 → 뒤 루프 축소).

**적용 범위 (over-application 가드)**: 아키텍처·모호한 리팩토링·낯선 API/SDK·과거결정 충돌 가능·다중에이전트 작업에만. 변수명 변경·한 줄 수정·명확한 boilerplate엔 생략 (Dual-Brain DON'T).

## Spawn prompt 5요소 강제 (agent-routing.md 이관 · MANDATORY · Anthropic 공식)

모든 subagent/teammate spawn prompt에 아래 5요소를 반드시 명시한다:

| 요소 | 내용 |
|------|------|
| objective | 작업 목표 1줄 — "왜 이걸 하는가" |
| output_format | 응답 형식 (글자수, 섹션, 표 등) |
| tools / sources | 사용 가능 도구·MCP·검색 범위 |
| task_boundary | 무엇을 하지 않을 것인가 (수정 금지/탐색만/...). 표준 문구 1개는 항상 포함: 다른 저장소는 읽기만, 수정 금지(프로젝트 경계 — `rules/code-execution.md`) |
| user_request | 사용자 지시 원문: 사용자가 실제로 쓴 문장의 인용(해당 부분) 또는 원문이 든 파일 경로. main 의 요약 · 해석만 넘기지 않는다 |

근거: Anthropic "Building effective agents" — 누락 시 작업 중복·누락 빈발.

**다섯째 요소(사용자 지시 원문)를 두는 까닭 (2026-11-24 사용자 결정, 의뢰서 `intent/2026-11-24-harness-review-six-items.md` W4)**: main 이 지시를 요약하는 단계에서 제약과 «하지 말 것» 이 빠지기 쉽다. 서브에이전트는 요약만 보고 다른 방향으로 일하고, 검수자도 요약과만 대조해 어긋남을 못 잡는다. 원문 한 토막이나 파일 경로를 함께 넘기면 받는 쪽이 직접 대조할 수 있다.

- **면제**: 조회 전용 에이전트(scout · searcher · citation-verifier)는 «사용자 지시 원문» 요소가 없어도 된다(사용자 결정 R3). 나머지 네 요소는 그대로 필요하다.
- **외부 글을 읽는 에이전트**: 원문 가운데 그 작업에 필요한 부분만 넘긴다(사용자 지시 전체를 외부 조회 맥락에 싣지 않는다).
- **서두**: `[SKILL_DEPTH: N]` 은 기존 규칙대로 서두에 둔다(§ 에이전트 spawn prompt 서두에 포함할 2가지). 검사 훅은 이것을 기록 항목으로만 본다.

### 표지 문자열 (검사 훅 `scripts/agent-prompt-gate.py` 와 글자까지 같다)

검사 훅은 지시문 안에 아래 문자열이 이름표 자리에 있는지만 본다(설정 정본 `config/agent-prompt-gate.json` 의 `markers`). 한글 표지나 영문 키 가운데 하나만 있으면 그 요소는 있는 것으로 본다.

| 요소 | 한글 표지 | 영문 키만 쓴 꼴 |
|------|-----------|-----------------|
| objective | `목표(objective)` | `objective` |
| user_request | `사용자 지시 원문` | `user_request` |
| tools / sources | `도구 · 자료(tools/sources)` | `tools/sources` |
| output_format | `출력 형식(output_format)` | `output_format` |
| task_boundary | `경계(task_boundary)` | `task_boundary` |

**이름표 자리 규칙 (2026-11-24 qa 재현 뒤 개정)**: 표지는 줄 머리에서 시작해야 한다. 표지 앞에는 공백(탭 · 전각 공백 · NBSP 포함) · `#` · `-` · `*` · `>` · `[` · 백틱과, 뒤에 공백이 붙은 번호(`1.` · `2)`)만 올 수 있다. 표지 바로 뒤에는 닫는 백틱 하나를 건너뛴 다음 줄 끝 · `:` · `)` · `]` · `**` · 공백+`(` 가운데 하나가 와야 한다(대소문자 무시, 한글 표지 · 영문 키 모두 같다). 그래서 `1. 목표(objective):` 와 백틱으로 감싼 키도 통과한다. 본문 문장 속 낱말은 세지 않는다. 종전의 단순 포함 판정에서는 `implement the objective function; tools: use ruff` 가 두 요소를 채웠고, 낱말 다섯 개만 한 줄에 늘어놓아도 통과했다. 영문 단독 `tools` 는 이 때문에 표지에서 뺐다.

- 통과: `## 목표(objective)` 처럼 줄 머리의 제목 / `- **task_boundary**: 쓰기 금지` 처럼 글머리표 이름표
- 불통과: `implement the objective function` 처럼 문장 속 낱말 / `objective user_request tools/sources output_format task_boundary` 처럼 한 줄에 늘어놓은 낱말(첫 낱말 뒤가 공백이라 이름표가 아니다)

검사 대상은 `rules/agent-routing.md` 에이전트 표의 이름이다(표 밖 타입 · 플러그인 타입 · `fork` 는 통과). 처음에는 기록만 하고(observe, `_audit/agent-prompt-gate.tsv`) 7일째 오탐 표(`agent-prompt-gate.py --report --days 7`)를 사용자에게 보고한 뒤 사용자 확인으로 거부(enforce)로 바꾼다(자동 전환 없음, 사용자 결정 R4).
- 기한 알림: main 이 등록할 때 `config/agent-prompt-gate.json` 의 `registered` 에 등록일(YYYY-MM-DD)을 적는다. 그날부터 7일이 지나면 하네스 저장소 세션의 시작 점검에 `AGENT_PROMPT_GATE_REPORT_DUE` 가 뜬다(`scripts/harness-usage-check.sh`). 표를 보고한 뒤 같은 파일의 `report_7d_done` 을 true 로 바꾸면 꺼진다. enforce 로 바꿔도 꺼진다.

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

## Spawn prompt 추가 지침 (Fable 5 공식 프롬프팅 가이드 이식, 2026-07-09: 5요소에 더해)

- **조기중단 방지**: spawn prompt에 "가역·저위험 단계는 중간 확인 질문("~할까요?")으로 블로킹하지 말고 완주하라" 포함 — 진짜 막힘·합의 필요 시에만 BLOCKED/NEEDS_CONTEXT로 main 반환 (기존 규약 유지).
- **시각화 산출물은 소집 전에 그릴 주체부터 (2026-11-10 사용자 결정)**: 그림 · 그림 스크립트 · html · svg · Artifact 페이지를 만들게 될 서브에이전트를 부르기 **전에** main 이 그릴 주체를 결정 팝업으로 먼저 묻는다. 답이 없으면 decision-popup mod 가 서브에이전트의 그 쓰기 · 실행 · 게시를 막아 main 으로 되돌아오는 왕복이 생긴다(정본 `skills/figure/SKILL.md` § 그릴 주체 선택).
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
| researcher | mem0 | 저장·검색·갱신 가능. 단 외부 원문을 읽은 흐름(paper-read 등)에서는 저장하지 않고 payload 반환, 저장은 main (`untrusted-quarantine.md` §2) |
| qa / gitops / scout / reviewer | mem0 | 저장·검색 위주 (reviewer 는 과거 QA 이력 검색 위주) |
| security | 없음 | 미부착 — Read·Grep·Glob·Bash 만 |
| tutor | mem0 | 저장·검색 가능 (쓰기는 재료 폴더 파일만, `agents/tutor.md`) |
| docs | 없음 (2026-11-10 글쓰기 전용) | 미부착 — 초안 파일만 쓰고 위키 조회·게시·Mem0 기록은 main (`skills/confluence/SKILL.md` §3-1) |

> **update_memory 주체**: 서브에이전트 중에서는 planner/researcher만(main 은 제한 없음) (3팀 Round 2 합의 + B4 중복 방지 — searcher는 2026-07-15 Mem0 제거로 대상 제외)
> **untrusted 격리 원칙**: 외부 공개 콘텐츠를 읽는 에이전트는 영속 메모리에 직접 쓰지 않는다 — `untrusted-quarantine.md` MCP 쓰기 금지 목록(Mem0 포함) 참조

### 미연결 처리
에이전트가 부착된 서버의 도구를 목록에서 찾지 못하면(OAuth 미연결·버전 회귀 등) 해당 MCP를 unavailable로 간주하고 BLOCKED로 main 보고 → main이 spawn prompt에 `[MEM0: unavailable]` 등 표시 후 재시도 또는 `mcp-fallback.md` 규칙 적용

## 전용 스킬 공유 조건 (H1b: MANDATORY, 2026-11-05 결정 · 2026-11-07 규칙화)

에이전트 정의 frontmatter 의 `skills:` 로 전용 스킬을 둘 이상의 에이전트가 함께 실으려면 아래 다섯 가지를 모두 지킨다. Claude Code 는 스킬을 특정 에이전트에 묶는 설정이 없어(공식 기능은 `skills:` 미리 적재뿐) 이 규칙이 유일한 통제다.

1. 판정 스킬(검수 · 채점 · 감사)은 그 산출물을 만든 에이전트와 공유하지 않는다. 자기 산출물을 자기 기준으로 채점하는 길을 막기 위해서다.
2. 스킬을 받는 에이전트의 도구 · MCP 가 순증가하지 않는다(스킬이 요구하는 도구를 이유로 tools · mcpServers 를 늘리지 않는다).
3. 외부 원문(웹 · 이슈 · 메일 · 외부 모델 답)을 읽는 스킬은 쓰기(Write · Edit) · Bash · 메모리 쓰기 권한이 있는 에이전트에 싣지 않는다(`untrusted-quarantine.md`).
4. 모델 하한: 스킬 정본이 요구하는 모델보다 낮은 모델의 에이전트에 싣지 않는다.
5. 편입할 때마다 쓰기 경계 검사와 주입 픽스처(fold-bench F2 꼴)로 «쓰기 · MCP 시도 0건» 을 확인한 뒤에 커밋한다.

- 하지 않는 편입(검수팀 반대, H1b): security → qa, reviewer → coder, citation-verifier → researcher.
- 기계 대조: fold-bench 정적 검사 S2 가 모든 agents frontmatter 의 `skills:` 를 이 다섯 조건과 대조한다(5번은 F2 결과로 판정).

## 에이전트 spawn prompt 반환 형식 가드레일 (MANDATORY)

모든 spawn prompt 에 반환 형식 제약 3줄을 넣는다. 반환 길이·적재 기준(100자·1500자·Write 없는 에이전트 예외)과 3줄 본문은 `rules-lazy/token-efficiency.md` § Subagent 반환값 적재 최소화 · § Agent Spawn Prompt 가드레일이 단일 정본이다. qa 의 검증 증거 보고는 이 상한의 예외이고 요약을 맨 앞에 둔다(같은 절).

## 장기 소집 정체 점검 (2026-11-12 후보 판정 G10)

main 은 스스로 깨어나지 못하고 알림이나 사용자 메시지로 턴이 열릴 때만 움직인다. 그래서 점검은 턴이 열렸을 때(다른 알림 · 사용자 메시지) 한다. 그때 돌고 있는 소집이 같은 역할의 직전 유사 작업보다 뚜렷이 길거나 15분을 넘겼으면, main 은 사용자가 묻기 전에 진행 여부(마지막 도구 호출 시각 · 산출 파일)를 확인해 한 줄로 알린다. 진행이 없으면 `TaskStop` 뒤 같은 명세로 재소집하고 그 사실을 보고한다.

- 이 한 줄은 `rules/agent-routing.md` «프롬프트 1회 = 보고 1회» 의 예외 4(장기 작업의 생존 신호 한 줄)에 해당한다. 15분 문턱은 그 예외를 언제 쓰는지 정한 구체 기준이다.

- 근거: 사용자 교정 «coder … 요약 작성 중 45m … 이건 언제까지 하는 거야»(T12-20261111-17) · «아직도 확인만 해? 너무 오래하는데»(T12-20261112-03).
