# 도구 접근 정책 — CLI/API vs MCP (효율 우선)

> **로드 시점**: 새 외부 서비스 연동 방식을 결정하거나, MCP 서버 추가/유지 여부를 판단할 때 lazy 로드.
> **근거**: Quandri "MCP is dead" (CLI-first + Skills) — MCP 도구 정의 상시 로드로 컨텍스트 잠식(77도구 ≈ 21K 토큰, 창의 10.5%), 호출당 3x·첫 호출 9.4x 지연, CLI/API와 기능 중복. + Anthropic Tom Tunguz "Harnessing AI" §2(Tools) §7(Cost).
> **핵심 원칙**: *"Teaching well matters more than connecting everything."* 연결을 늘리기보다, 필요한 것만 on-demand로 가르친다.

---

## §1 선택 우선순위 (위에서부터 적용)

```
1. 강력한 CLI가 있는가? (gh, psql, aws, curl+jq 등 LLM이 이미 아는 도구)
   YES → CLI를 Bash로 직접 사용 (컨텍스트 0) 또는 사용법을 Skill에 임베드
2. CLI는 없지만 단순 REST/HTTP API가 있는가?
   YES → curl 사용법을 Skill에 임베드 (on-demand 로드)
3. 위가 불가하거나, 아래 "MCP 정당화 조건"에 해당하는가?
   YES → MCP 사용 (단 deferred loading 필수)
```

## §2 MCP 정당화 조건 (아래 중 하나 충족 시에만 MCP 채택)

| 조건 | 예 |
|------|-----|
| 강력한 CLI/API 부재 | 전용 프로토콜만 제공하는 서비스 |
| 팀 공유 인증·credential 격리 필요 | 프로덕션 DB, 공유 워크스페이스 |
| 서버측 쿼리 검증·접근제어 필요 (안전 게이트) | `DROP TABLE` 등 위험 쿼리 차단 |
| 영구 상태·메모리 동기화 | 메모리 백엔드 |

> 위 조건 미해당 + 강력 CLI 존재 → **MCP 금지, CLI/Skill 사용.**

## §3 본 하네스 적용 현황 (정책 일치)

| 서비스 | 현재 방식 | 정책 판정 |
|--------|----------|----------|
| git / GitHub | `gh` CLI + Bash(git) | ✅ CLI-first (정석) |
| Mem0 | MCP | ✅ 정당화(영구 메모리·동기화·fallback 보유) |
| Tavily / 검색 | MCP (searcher 경유) | 🔶 허용(결과 파싱 편의) — curl 대체 가능하나 marginal |
| context7 (라이브러리 문서) | MCP | ✅ 허용(Anthropic 권장, 전용 검색) |
| arxiv / scientific-papers | MCP | 🔶 검토(arXiv는 단순 HTTP API — Skill+curl 대체 후보) |
| Confluence/Jira | claude.ai Atlassian 커넥터 (OAuth MCP — docs 에이전트 경유) | ✅ 정당화(강력 CLI 부재 + 공유 인증) |

## §4 MCP 사용 시 의무 (채택했다면)

- **deferred loading 필수 (main 컨텍스트)**: 도구 정의를 상시 로드하지 않고 `ToolSearch("select:...")`로 호출 직전 적재 (`rules/mem0-auto.md` §0 패턴). Anthropic Tool Search로 MCP 컨텍스트 85%+ 절감. **단 subagent는 예외** — 프론트매터 `mcpServers`에 부착된 도구가 spawn 시 사전 로드되므로 ToolSearch 불요(2026-07-15 실측 `agent-routing-mcp.md`·`searcher.md`). deferred loading은 main의 deferred 도구에만 적용.
- **연결 최소화**: 현재 워크플로우에서 실제 쓰는 서버만 연결 유지. 미사용 커넥터는 disconnect (deferred여도 도구 이름 목록 + init/신뢰성 표면 비용 존재).
- **가용성 점검**: 호출 전 `rules-lazy/mcp-health-check.md`, 미연결 시 `rules-lazy/mcp-fallback.md`.
- **untrusted 격리**: 외부 콘텐츠 fetch MCP는 `rules-lazy/untrusted-quarantine.md` 적용.

## §5 신규 연동 요청 시 체크리스트

새 도구/서비스 연동 요청을 받으면 §1 우선순위로 1줄 보고:
```
"{서비스}는 {CLI 있음/API 있음/전용프로토콜}이라 → {Bash CLI / Skill+curl / MCP}로 연동 권장. 이유: {1줄}."
```
사용자가 MCP를 명시 요청하면 그대로 진행하되, §2 정당화 조건 미해당 시 CLI 대안을 1줄 푸시백.
