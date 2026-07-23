# MCP Fallback — Mem0

> **핵심 원칙**: MCP 불가 시 **스킵 금지** — 반드시 대체 수단으로 전환한다.
> **공통 원칙 전문**: `~/.claude/rules-lazy/mcp-fallback.md` 참조

## § Mem0 Fallback

### Mem0 가용성 체크

> 자동 트리거 규칙: `~/.claude/rules/mem0-auto.md` 참조

세션 내 첫 Mem0 호출 전 MCP 연결 상태를 확인한다:

```
1. Mem0 MCP 도구 존재 여부 확인 (ToolSearch "mem0")
   → 도구명: add_memory, search_memories, get_memories, update_memory, delete_memory
2. 존재 → 정상 진행
3. 미존재 → Mem0 불가 상태 선언 → 모든 Mem0 호출을 fallback으로 전환
```

### Fallback 규칙

Mem0 불가 시 아래 원칙을 적용한다:

| 원칙 | 내용 |
|------|------|
| **스킵 금지** | "Mem0가 없으니 생략" 절대 금지 — fallback 실행 필수 |
| **파일 대체** | Mem0 저장 → long-term/ 파일 기록으로 대체 |
| **검색 대체** | Mem0 검색 → long-term/ + short-term/ 파일 Grep으로 대체 |
| **사용자 알림** | 첫 fallback 발생 시 1회 알림: "Mem0 미연결 — 파일 기록으로 대체합니다" |

### Fallback 매핑 (Category → 파일)

> 아래 `long-term/` = `${LONG_TERM_ROOT}` (canonical: `~/workspace/_data/workspaces/user/.claude/long-term/`) — `~/.claude/long-term` 생성 금지.

#### 저장 (add_memory → Write)

| Mem0 category | Fallback 파일 | 형식 |
|---------------|--------------|------|
| `decision` | `short-term/decisions.md` | 기존 memory-write.md 형식 |
| `discuss` | `long-term/{project}/meetings/` 하위 회의록 | 기존 discuss 회의록 형식 |
| `paper` | `long-term/experiments.md` § 논문 참조 | `- [날짜] {논문제목}: {요약}` |
| `experiment` | `long-term/experiments.md` | 기존 형식 |
| `code_pattern` | `long-term/feedback.md` § 코드 패턴 | `- [날짜] {모듈}: {패턴 요약}` (코딩 컨벤션 포함 — source=coding-conventions) |
| `context` | `short-term/handover.md` | 기존 형식 |
| `feedback` | `long-term/feedback.md` | 기존 형식 |

#### 검색 (search_memories → Grep)

| Mem0 검색 | Fallback 방법 |
|-----------|-------------|
| `category="discuss"` | `Grep(pattern="{query}", path="long-term/{project}/meetings/")` |
| `category="paper"` | `Grep(pattern="{query}", path="long-term/experiments.md")` |
| `category="decision"` | `Grep(pattern="{query}", path="short-term/decisions.md")` + `Grep(path="long-term/")` |
| `category="code_pattern"` | `Grep(pattern="{query}", path="long-term/feedback.md")` |
| `category="experiment"` | `Grep(pattern="{query}", path="long-term/experiments.md")` |
| `category="feedback"` | `Grep(pattern="{query}", path="long-term/feedback.md")` |
| `category="context"` | `Grep(pattern="{query}", path="short-term/handover.md")` |
| 전체 크로스 검색 | `Grep(pattern="{query}", path="long-term/")` + `Grep(path="short-term/")` |
