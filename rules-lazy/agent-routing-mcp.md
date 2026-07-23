# 에이전트 시스템 — MCP 부착 정책 + spawn 가드레일 (lazy)

> **로드 시점**: 에이전트 spawn 직전 (subagent/teammate 호출 시)
> **상위 파일**: `~/.claude/rules/agent-routing.md`

## MCP 도구 로딩의 실제 메커니즘 (2026-07-15 전면 개정 — GPT 교차감사 P1-1)

에이전트의 MCP 도구는 `agents/*.md` frontmatter의 **`mcpServers:` 필드가 결정**하며, 부착된
서버의 도구 스키마는 **spawn 시 이미 로드**되어 있다 (Claude Code 2.1.210 실측 —
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
| qa / gitops / designer / scout | mem0 | 저장·검색 위주 |
| docs | claude_ai_Atlassian, mem0 | 저장·검색 가능 (Confluence 쓰기는 사용자 승인 게이트) |

> **update_memory 주체**: planner/researcher만 (3팀 Round 2 합의 + B4 중복 방지 — searcher는 2026-07-15 Mem0 제거로 대상 제외)
> **untrusted 격리 원칙**: 외부 공개 콘텐츠를 읽는 에이전트는 영속 메모리에 직접 쓰지 않는다 — `untrusted-quarantine.md` MCP 쓰기 금지 목록(Mem0 포함) 참조

### 미연결 처리
에이전트가 부착된 서버의 도구를 목록에서 찾지 못하면(OAuth 미연결·버전 회귀 등) 해당 MCP를 unavailable로 간주하고 BLOCKED로 main 보고 → main이 spawn prompt에 `[MEM0: unavailable]` 등 표시 후 재시도 또는 `mcp-fallback.md` 규칙 적용

## 에이전트 spawn prompt 반환 형식 가드레일 (MANDATORY)

모든 spawn prompt에 아래 3줄 자동 포함 (main 컨텍스트 보호 — `rules-lazy/token-efficiency.md` § Subagent 반환값 적재 최소화 참조):

```
## 반환 형식 제약 (main 컨텍스트 보호)
- 전체 반환 1500자 이내
- 상세 데이터는 `_workspace/{agent}_{주제}.md` 저장 후 경로만 반환
  (**Write 미보유 에이전트(searcher/scout/planner/gitops/citation-verifier)는 저장 불가 → 압축 요약 직접 반환**; token-efficiency.md § 반환 형식 제약과 동일 예외)
- raw JSON/로그 원문 복사 금지, 요약만
```

> 1M context 세션에서 subagent 반환값이 누적되어 200K 돌파 시 Extra usage API 에러 발생.

(2026-04-19 1M 가드레일 신설)

## 적재 기준 강화 (planner 제안 A 적용)

main 컨텍스트 보호를 위해 반환값 적재 기준을 강화한다:

| 반환 크기 | 처리 |
|----------|------|
| **100자 이하** | main 직접 적재 (요약·결정·결과 한 줄) |
| **100자 초과 ~ 1500자** | `_workspace/{agent}_{주제}.md` 저장 후 경로만 반환 |
| **1500자 초과** | 위와 동일 + 반환 prompt 거부 (재시도 요청) |

> 기존 "1500자 이내" 룰은 상한이며, **권장값은 100자 이하**. 100자 초과 시 자동 파일 경유.

### 효과
- 한 세션에서 subagent 30~50회 호출 시 누적 절감: ~150K → ~30K 토큰 (100자 × 50회 = 5K + 파일 경로 참조 ~50K)
- 200K Extra usage 경계 회피
